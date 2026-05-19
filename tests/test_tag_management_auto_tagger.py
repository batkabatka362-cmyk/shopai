"""Tests for ``engines.tag_management.auto_tagger.auto_tag``.

Focused on the niche-aware path added on top of the original
title-keyword + price-tier + attribute extraction logic.

Coverage:
  1. Pre-niche behaviour unchanged: title keyword extraction,
     stop word filtering, category, price tier, attributes.
  2. Niche=None / "" / whitespace -> behaves as before (no
     niche suggestions).
  3. Niche supplied + tag_library available -> niche tags
     surface in output.
  4. Niche tags merge cleanly with title-keyword tags
     (dedupe + order preserved).
  5. Niche suggester raise doesn't poison the whole batch.
  6. Unknown niche falls back to general taxonomy without
     erroring.
  7. New niche-derived tags surface in `new_tags_discovered`.
"""
from __future__ import annotations

from unittest.mock import patch

from engines.tag_management.auto_tagger import auto_tag


# ── Pre-niche behaviour ──────────────────────────────────────


class TestPreNicheBehaviour:

    def test_title_keywords_extracted(self):
        out = auto_tag(
            products=[{
                "id": "p1",
                "title": "Vitamin C Hydration Serum",
            }],
            existing_tags=[],
        )
        tags = out["assignments"][0]["tags"]
        # Stop words filtered + 3+ letter words kept
        assert "vitamin" in tags
        assert "hydration" in tags
        assert "serum" in tags

    def test_price_tier_below_20(self):
        out = auto_tag(
            products=[{
                "id": "p1", "title": "Cheap thing",
                "price": 12,
            }],
            existing_tags=[],
        )
        tags = out["assignments"][0]["tags"]
        assert "affordable" in tags

    def test_price_tier_premium(self):
        out = auto_tag(
            products=[{
                "id": "p1", "title": "Pricey thing",
                "price": 150,
            }],
            existing_tags=[],
        )
        tags = out["assignments"][0]["tags"]
        assert "premium" in tags

    def test_attributes_emitted(self):
        out = auto_tag(
            products=[{
                "id": "p1",
                "title": "Stuff",
                "material": "Cotton",
                "color": "BLUE",
            }],
            existing_tags=[],
        )
        tags = out["assignments"][0]["tags"]
        assert "cotton" in tags
        assert "blue" in tags

    def test_no_niche_no_niche_call(self):
        """When niche is None, tag_library suggester is never
        invoked -- pre-niche callers see byte-for-byte
        identical output."""
        with patch(
            "engines.store_setup.tag_library."
            "suggest_tags_for_product"
        ) as mock_suggest:
            auto_tag(
                products=[{
                    "id": "p1", "title": "Plain",
                }],
                existing_tags=[],
            )
        mock_suggest.assert_not_called()

    def test_blank_niche_no_call(self):
        with patch(
            "engines.store_setup.tag_library."
            "suggest_tags_for_product"
        ) as mock_suggest:
            auto_tag(
                products=[{"id": "p1", "title": "Plain"}],
                existing_tags=[],
                niche="",
            )
            auto_tag(
                products=[{"id": "p1", "title": "Plain"}],
                existing_tags=[],
                niche="   ",
            )
        mock_suggest.assert_not_called()


# ── Niche-aware path ─────────────────────────────────────────


class TestNicheAwarePath:

    def test_niche_tags_surface_in_output(self):
        """Beauty product with hydration in the title gets
        beauty-niche tags (concern:hydration, etc.)."""
        out = auto_tag(
            products=[{
                "id": "p1",
                "title": "Hydration Serum",
                "body_html": "Fragrance-free formula",
            }],
            existing_tags=[],
            niche="beauty",
        )
        tags = out["assignments"][0]["tags"]
        assert "concern:hydration" in tags
        assert "texture:serum" in tags
        assert "claims:fragrance-free" in tags

    def test_niche_tags_merge_with_title_keywords(self):
        """Both title keywords AND niche tags appear; no
        crosstalk / loss."""
        out = auto_tag(
            products=[{
                "id": "p1",
                "title": "Hydration Serum",
            }],
            existing_tags=[],
            niche="beauty",
        )
        tags = out["assignments"][0]["tags"]
        # Title keywords still there
        assert "hydration" in tags
        assert "serum" in tags
        # Niche-aware ones added
        assert "concern:hydration" in tags
        assert "texture:serum" in tags

    def test_dedup_preserved(self):
        """No duplicate tags in the final list."""
        out = auto_tag(
            products=[{
                "id": "p1",
                "title": "Hydration Serum",
            }],
            existing_tags=[],
            niche="beauty",
        )
        tags = out["assignments"][0]["tags"]
        assert len(tags) == len(set(tags))

    def test_unknown_niche_falls_back_to_general(self):
        """Unknown niches don't raise -- they fall back to
        the general taxonomy."""
        out = auto_tag(
            products=[{
                "id": "p1",
                "title": "Gift item",
                "body_html": "Best for the holidays",
            }],
            existing_tags=[],
            niche="ufo_parts",
        )
        # General taxonomy has occasion:gift; title contains
        # 'gift'.
        tags = out["assignments"][0]["tags"]
        assert "occasion:gift" in tags

    def test_fitness_niche(self):
        out = auto_tag(
            products=[{
                "id": "p1",
                "title": "Running shorts",
                "body_html": "Moisture-wicking + breathable",
            }],
            existing_tags=[],
            niche="fitness",
        )
        tags = out["assignments"][0]["tags"]
        assert "activity:running" in tags
        assert "claims:moisture-wicking" in tags

    def test_new_niche_tags_in_discovered_set(self):
        """Niche tags that aren't in existing_tags surface
        as `new_tags_discovered`."""
        out = auto_tag(
            products=[{
                "id": "p1",
                "title": "Hydration Serum",
            }],
            existing_tags=[],  # no known tags
            niche="beauty",
        )
        discovered = set(out["new_tags_discovered"])
        # Niche-derived tags also count as discovered
        assert "concern:hydration" in discovered
        assert "texture:serum" in discovered


class TestRobustness:

    def test_niche_suggester_raise_doesnt_block(self):
        """A raising tag_library doesn't poison the batch
        -- the product still gets its title-keyword tags."""
        with patch(
            "engines.store_setup.tag_library."
            "suggest_tags_for_product",
            side_effect=RuntimeError("boom"),
        ):
            out = auto_tag(
                products=[{
                    "id": "p1",
                    "title": "Hydration Serum",
                }],
                existing_tags=[],
                niche="beauty",
            )
        assert out["status"] == "success"
        tags = out["assignments"][0]["tags"]
        # Title keywords still emitted
        assert "hydration" in tags
        # No niche tags (the suggester raised)
        assert "concern:hydration" not in tags

    def test_missing_tag_library_module_falls_back(self):
        """If tag_library is somehow unavailable, the
        niche-aware path silently falls back to pre-niche
        behaviour. Simulated by patching the import to
        raise."""
        # Patch the actual import path so the
        # _resolve_niche_tagger import fails.
        import builtins
        real_import = builtins.__import__

        def _bad_import(name, *args, **kwargs):
            if "tag_library" in name:
                raise ImportError("simulated missing module")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_bad_import):
            out = auto_tag(
                products=[{
                    "id": "p1",
                    "title": "Hydration Serum",
                }],
                existing_tags=[],
                niche="beauty",
            )
        assert out["status"] == "success"
        tags = out["assignments"][0]["tags"]
        # Title keywords -- pre-niche path
        assert "hydration" in tags
        # No niche tags (module unavailable)
        assert "concern:hydration" not in tags

    def test_multiple_products_independent(self):
        """One bad product doesn't affect tagging of
        others."""
        out = auto_tag(
            products=[
                {"id": "p1", "title": "Hydration Serum"},
                {"id": "p2", "title": "Anti-aging Cream"},
            ],
            existing_tags=[],
            niche="beauty",
        )
        # Both got niche-aware tags
        tags_p1 = out["assignments"][0]["tags"]
        tags_p2 = out["assignments"][1]["tags"]
        assert "concern:hydration" in tags_p1
        # 'Anti-aging Cream' has texture cream + concern
        assert "texture:cream" in tags_p2
        assert "concern:anti-aging" in tags_p2
