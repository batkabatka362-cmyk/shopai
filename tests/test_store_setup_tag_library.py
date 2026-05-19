"""Tests for ``engines.store_setup.tag_library``.

Read-only reference data: niche-aware canonical tag
taxonomies + helpers for tag suggestion + merge.

Coverage:
  1. `get_niche_tags`: per-niche shape, fallback for
     unknown niche, deep-copy semantics (caller mutation
     doesn't poison the library).
  2. Every shipped niche has 3+ families with 3+ values.
  3. `flatten_to_tags`: prefixed + bare modes, dedupe,
     empty inputs.
  4. `suggest_tags_for_product`: matches against title /
     body / tags / product_type / vendor; matches both
     slug + spaced forms; respects max_per_family; handles
     non-dict / empty input.
  5. `merge_suggested_with_existing`: dedupes
     case-insensitively, existing-wins order, handles
     None / non-iterables.
"""
from __future__ import annotations

from engines.store_setup.tag_library import (
    _NICHE_TAG_FAMILIES,
    flatten_to_tags,
    get_niche_tags,
    merge_suggested_with_existing,
    suggest_tags_for_product,
)


# ── get_niche_tags ────────────────────────────────────────────


class TestGetNicheTags:

    def test_beauty_has_skin_type_family(self):
        spec = get_niche_tags("beauty")
        assert spec["niche"] == "beauty"
        assert "skin-type" in spec["families"]
        assert "dry" in spec["families"]["skin-type"]

    def test_unknown_niche_falls_back_to_general(self):
        spec = get_niche_tags("ufo_parts")
        assert spec["niche"] == "ufo_parts"
        # families match general's
        assert (
            set(spec["families"].keys())
            == set(_NICHE_TAG_FAMILIES["general"].keys())
        )

    def test_blank_niche_falls_back(self):
        assert get_niche_tags("")["families"] == get_niche_tags(
            "general",
        )["families"]
        assert get_niche_tags(None)["families"] == get_niche_tags(  # type: ignore[arg-type]
            "general",
        )["families"]

    def test_caller_cannot_mutate_library(self):
        """Caller mutation of the returned families list
        must not poison the module-level taxonomy."""
        spec = get_niche_tags("beauty")
        spec["families"]["skin-type"].append("ufo")
        # Fetch again - should not see the mutation
        spec2 = get_niche_tags("beauty")
        assert "ufo" not in spec2["families"]["skin-type"]


class TestNicheCoverage:
    """Every shipped niche must have a real taxonomy --
    not just the placeholder shape."""

    def test_every_niche_has_three_plus_families(self):
        for niche, families in _NICHE_TAG_FAMILIES.items():
            assert len(families) >= 3, niche

    def test_every_family_has_three_plus_values(self):
        for niche, families in _NICHE_TAG_FAMILIES.items():
            for family_name, values in families.items():
                assert len(values) >= 3, (niche, family_name)

    def test_all_values_are_slug_cased(self):
        """Tag values must be lowercase + hyphenated --
        matches Shopify's tag convention."""
        for niche, families in _NICHE_TAG_FAMILIES.items():
            for family_name, values in families.items():
                for value in values:
                    assert value == value.lower(), (
                        niche, family_name, value,
                    )
                    assert " " not in value, (
                        niche, family_name, value,
                    )

    def test_extended_niches_all_present(self):
        """All 10 specific niches + general are taxonomied."""
        expected = {
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general",
        }
        assert set(_NICHE_TAG_FAMILIES.keys()) == expected


# ── flatten_to_tags ─────────────────────────────────────────


class TestFlatten:

    def test_prefixed_mode(self):
        families = {
            "skin-type": ["oily", "dry"],
            "concern": ["hydration"],
        }
        out = flatten_to_tags(families)
        assert "skin-type:oily" in out
        assert "skin-type:dry" in out
        assert "concern:hydration" in out
        assert len(out) == 3

    def test_bare_mode(self):
        families = {
            "skin-type": ["oily", "dry"],
        }
        out = flatten_to_tags(families, include_prefix=False)
        assert out == ["oily", "dry"]

    def test_dedupes_across_families(self):
        """Same value in two families (e.g. 'minimalist'
        could be in style AND philosophy) -- when
        include_prefix=False they collide; dedup keeps
        first occurrence."""
        families = {
            "fit": ["regular"],
            "fit-type": ["regular"],
        }
        out = flatten_to_tags(families, include_prefix=False)
        assert out == ["regular"]

    def test_empty(self):
        assert flatten_to_tags({}) == []
        assert flatten_to_tags(None) == []  # type: ignore[arg-type]

    def test_skips_non_string_values(self):
        families = {
            "x": ["a", 42, "b", "", "   ", None],
        }
        out = flatten_to_tags(families)
        assert out == ["x:a", "x:b"]


# ── suggest_tags_for_product ────────────────────────────────


class TestSuggestTags:

    def test_matches_against_title(self):
        product = {
            "title": "Vitamin C Hydration Serum",
            "body_html": "",
        }
        out = suggest_tags_for_product(
            product, niche="beauty",
        )
        # "hydration" hits beauty -> concern:hydration
        assert "concern:hydration" in out
        # "serum" hits beauty -> texture:serum
        assert "texture:serum" in out

    def test_matches_in_body_html(self):
        product = {
            "title": "Plain Title",
            "body_html": (
                "<p>This non-comedogenic formula is "
                "fragrance-free.</p>"
            ),
        }
        out = suggest_tags_for_product(
            product, niche="beauty",
        )
        assert "claims:non-comedogenic" in out
        assert "claims:fragrance-free" in out

    def test_strips_html_tags_from_body(self):
        """HTML tag names shouldn't accidentally match
        tag values (e.g. <li> matching 'li')."""
        product = {
            "title": "Plain",
            "body_html": "<oily><dry>",
        }
        out = suggest_tags_for_product(
            product, niche="beauty",
        )
        # <oily> + <dry> are HTML tags -- stripped before
        # matching -- shouldn't surface as suggestions.
        assert "skin-type:oily" not in out
        assert "skin-type:dry" not in out

    def test_matches_spaced_form(self):
        """`anti-aging` in the library should still match
        when the product text says 'anti aging'."""
        product = {
            "title": "Anti aging serum",
            "body_html": "",
        }
        out = suggest_tags_for_product(
            product, niche="beauty",
        )
        assert "concern:anti-aging" in out

    def test_max_per_family_caps_suggestions(self):
        """Beauty's `concern` family has 7 values -- a
        product matching all of them should still cap to
        max_per_family."""
        product = {
            "title": "hydration anti aging brightening",
            "body_html": "for blemishes and redness",
        }
        out = suggest_tags_for_product(
            product, niche="beauty", max_per_family=2,
        )
        concern_tags = [
            t for t in out if t.startswith("concern:")
        ]
        assert len(concern_tags) == 2

    def test_non_dict_input(self):
        assert suggest_tags_for_product(None) == []  # type: ignore[arg-type]
        assert suggest_tags_for_product("") == []  # type: ignore[arg-type]

    def test_empty_product(self):
        assert suggest_tags_for_product({}) == []

    def test_tags_field_searched(self):
        """If existing tags include keywords (e.g.
        'organic-cotton'), the matcher should pick that
        up too."""
        product = {
            "title": "Baby onesie",
            "body_html": "",
            "tags": ["organic-cotton", "soft"],
        }
        out = suggest_tags_for_product(
            product, niche="baby",
        )
        assert "material:organic-cotton" in out


# ── merge_suggested_with_existing ───────────────────────────


class TestMerge:

    def test_existing_wins_at_front(self):
        out = merge_suggested_with_existing(
            existing=["a", "b"],
            suggested=["c", "d"],
        )
        assert out == ["a", "b", "c", "d"]

    def test_case_insensitive_dedup(self):
        out = merge_suggested_with_existing(
            existing=["Vegan"],
            suggested=["vegan", "VEGAN"],
        )
        assert out == ["Vegan"]

    def test_existing_priority_on_duplicate(self):
        """Existing tag preserves operator's casing even
        when suggested duplicate exists."""
        out = merge_suggested_with_existing(
            existing=["Skin-Type:Dry"],
            suggested=["skin-type:dry"],
        )
        assert out == ["Skin-Type:Dry"]

    def test_none_inputs(self):
        assert merge_suggested_with_existing(None, None) == []
        assert merge_suggested_with_existing(
            None, ["a"],
        ) == ["a"]
        assert merge_suggested_with_existing(
            ["a"], None,
        ) == ["a"]

    def test_skips_blank_and_non_string(self):
        out = merge_suggested_with_existing(
            existing=["a", "", "  ", None, 42, "b"],  # type: ignore[list-item]
            suggested=["c"],
        )
        assert out == ["a", "b", "c"]

    def test_preserves_order(self):
        out = merge_suggested_with_existing(
            existing=["z", "a"],
            suggested=["m", "b"],
        )
        assert out == ["z", "a", "m", "b"]
