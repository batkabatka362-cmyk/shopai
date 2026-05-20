"""Tests for ``engines.store_setup.homepage_sections``.

Generator recommends a niche-aware section order; applier
persists as Shopify page (``homepage-sections``) via
``SHOPIFY_CREATE_PAGE``. Records via Pattern Z.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: every niche has at least 5 sections.
  3. Generator: each section has name + rationale +
     above_fold boolean.
  4. Generator: first 3 sections marked above_fold;
     others marked below_fold.
  5. Generator: Hero always present + first.
  6. Generator: Footer always present + last.
  7. Generator: subscription-natural niches (food / pets /
     baby) carry Subscription Pitch above the fold.
  8. Generator: jewelry has Craftsmanship Story.
  9. Generator: outdoor has Trail Stories.
 10. Generator: unknown niche -> general (no
     niche-specific sections).
 11. Generator: ranking_notes present + explains fold
     convention.
 12. Renderer: empty / non-dict.
 13. Renderer: produces ordered list + fold badges.
 14. Renderer: HTML-escapes content.
 15. Applier: empty short-circuit.
 16. Applier: success + Pattern Z metrics.
 17. Applier: router_unavailable / rejection / raise.
 18. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.homepage_sections import (
    _NICHE_ORDERS,
    _NICHE_SPECIFIC_SECTIONS,
    apply_sections,
    recommend_homepage_sections,
    render_sections_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert recommend_homepage_sections(
            store_name="",
        ) == {}
        assert recommend_homepage_sections(
            store_name="   ",
        ) == {}
        assert recommend_homepage_sections(
            store_name=None,
        ) == {}


class TestGeneratorShape:

    def test_at_least_five_sections_per_niche(self):
        for niche in _NICHE_ORDERS:
            spec = recommend_homepage_sections(
                store_name="Acme", niche=niche,
            )
            assert len(spec["sections"]) >= 5, niche

    def test_each_section_has_full_shape(self):
        for niche in _NICHE_ORDERS:
            spec = recommend_homepage_sections(
                store_name="Acme", niche=niche,
            )
            for section in spec["sections"]:
                assert section["name"], niche
                assert section["rationale"], niche
                assert isinstance(
                    section["above_fold"], bool,
                )

    def test_first_three_above_fold(self):
        spec = recommend_homepage_sections(
            store_name="Acme", niche="beauty",
        )
        for i, section in enumerate(spec["sections"]):
            if i < 3:
                assert section["above_fold"] is True, i
            else:
                assert section["above_fold"] is False, i

    def test_hero_always_first(self):
        for niche in _NICHE_ORDERS:
            spec = recommend_homepage_sections(
                store_name="Acme", niche=niche,
            )
            assert spec["sections"][0]["name"] == "Hero", (
                niche
            )

    def test_footer_always_last(self):
        for niche in _NICHE_ORDERS:
            spec = recommend_homepage_sections(
                store_name="Acme", niche=niche,
            )
            assert (
                spec["sections"][-1]["name"] == "Footer"
            ), niche

    def test_ranking_notes_present(self):
        spec = recommend_homepage_sections(
            store_name="Acme",
        )
        notes = spec["ranking_notes"].lower()
        assert "above-the-fold" in notes


class TestNicheSpecific:

    def test_food_has_subscription_above_fold(self):
        spec = recommend_homepage_sections(
            store_name="Acme", niche="food",
        )
        sub_section = next(
            (s for s in spec["sections"]
             if s["name"] == "Subscription Pitch"),
            None,
        )
        assert sub_section is not None
        assert sub_section["above_fold"] is True
        # Niche-specific rationale (not the universal one)
        assert (
            "repeat-purchase" in sub_section["rationale"]
            or "cadence" in sub_section["rationale"]
        )

    def test_pets_has_subscription_pitch(self):
        spec = recommend_homepage_sections(
            store_name="Acme", niche="pets",
        )
        names = [s["name"] for s in spec["sections"]]
        assert "Subscription Pitch" in names

    def test_baby_has_subscription_pitch(self):
        spec = recommend_homepage_sections(
            store_name="Acme", niche="baby",
        )
        names = [s["name"] for s in spec["sections"]]
        assert "Subscription Pitch" in names

    def test_jewelry_has_craftsmanship_story(self):
        spec = recommend_homepage_sections(
            store_name="Acme", niche="jewelry",
        )
        names = [s["name"] for s in spec["sections"]]
        assert "Craftsmanship Story" in names
        # Above the fold (high-consideration buy needs
        # trust before products)
        craft = next(
            s for s in spec["sections"]
            if s["name"] == "Craftsmanship Story"
        )
        assert craft["above_fold"] is True

    def test_outdoor_has_trail_stories(self):
        spec = recommend_homepage_sections(
            store_name="Acme", niche="outdoor",
        )
        names = [s["name"] for s in spec["sections"]]
        assert "Trail Stories" in names

    def test_unknown_niche_uses_general(self):
        spec = recommend_homepage_sections(
            store_name="Acme", niche="ufo_parts",
        )
        names = [s["name"] for s in spec["sections"]]
        general_names = _NICHE_ORDERS["general"]
        assert names == general_names

    def test_general_has_no_niche_specifics(self):
        """General falls back to universal-only --
        shouldn't have Subscription / Craftsmanship /
        Trail sections."""
        spec = recommend_homepage_sections(
            store_name="Acme", niche="general",
        )
        names = [s["name"] for s in spec["sections"]]
        for special in (
            "Subscription Pitch",
            "Craftsmanship Story",
            "Trail Stories",
        ):
            assert special not in names

    def test_niche_specific_sections_have_rationales(self):
        """Every niche-specific section has its own
        rationale entry (not the generic fallback)."""
        for niche, sections in (
            _NICHE_SPECIFIC_SECTIONS.items()
        ):
            for section_name, rationale in (
                sections.items()
            ):
                # Spot-check: rationale should be specific
                # not the generic "Custom section."
                # placeholder
                assert (
                    rationale != "Custom section."
                ), (niche, section_name)
                assert len(rationale) >= 30, (
                    niche, section_name,
                )


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_sections_html({}) == ""
        assert render_sections_html(None) == ""  # type: ignore[arg-type]
        assert (
            render_sections_html({"store_name": "Acme"})
            == ""
        )

    def test_produces_ordered_list(self):
        spec = recommend_homepage_sections(
            store_name="Acme", niche="beauty",
        )
        html_out = render_sections_html(spec)
        assert "<ol" in html_out
        # Numbered prefixes: 1. 2. 3. etc.
        assert "1. Hero" in html_out
        # Above-fold badge on the first 3
        assert (
            html_out.count("Above the fold") == 3
        )
        # Below-fold badge on the rest
        assert "Below the fold" in html_out

    def test_renders_for_niche_specific(self):
        spec = recommend_homepage_sections(
            store_name="Acme", niche="food",
        )
        html_out = render_sections_html(spec)
        # The niche-specific section renders
        assert "Subscription Pitch" in html_out

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "beauty",
            "sections": [
                {
                    "name": "<b>S</b>",
                    "rationale": "x & y",
                    "above_fold": True,
                },
            ],
            "ranking_notes": "<i>notes</i>",
        }
        html_out = render_sections_html(spec)
        assert "<script>x</script>" not in html_out
        assert "<b>S</b>" not in html_out
        assert "&lt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_sections({})
        assert out["applied"] is False
        assert out["error"] == "no_sections_spec"

    def test_non_dict(self):
        out = apply_sections(None)  # type: ignore[arg-type]
        assert out["applied"] is False

    def test_spec_without_sections(self):
        out = apply_sections({"store_name": "Acme"})
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = recommend_homepage_sections(
            store_name="Acme", niche="food",
        )
        with patch(
            "engines.store_setup.homepage_sections."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.homepage_sections."
            "record_writeback",
        ) as record_mock:
            out = apply_sections(spec)
        assert out["applied"] is True
        assert out["handle"] == "homepage-sections"
        params = router.execute.call_args.args[1]
        assert params["title"] == "Homepage Section Order"
        assert params["handle"] == "homepage-sections"
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        # Food has 7 sections (Hero, Sub Pitch, Featured Coll,
        # Featured Prods, Reviews, Newsletter, Footer)
        assert kwargs["metrics"]["section_count"] == 7
        assert kwargs["metrics"]["niche"] == "food"


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = recommend_homepage_sections(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.homepage_sections."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.homepage_sections."
            "record_writeback",
        ) as record_mock:
            out = apply_sections(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        assert (
            record_mock.call_args.kwargs["success"]
            is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = recommend_homepage_sections(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.homepage_sections."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.homepage_sections."
            "record_writeback",
        ):
            out = apply_sections(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = recommend_homepage_sections(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.homepage_sections."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.homepage_sections."
            "record_writeback",
        ):
            out = apply_sections(spec)
        assert out["applied"] is False
        assert "network" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = recommend_homepage_sections(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.homepage_sections."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.homepage_sections."
            "record_writeback",
        ) as record_mock:
            apply_sections(spec, store_id="store-a")
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
