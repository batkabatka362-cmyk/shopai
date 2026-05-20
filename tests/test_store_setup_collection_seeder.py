"""Tests for ``engines.store_setup.collection_seeder``.

Generates niche-specific starter collection specs and pushes
them via ``SHOPIFY_CREATE_COLLECTION``. Each push records via
Pattern Z so the autonomous learning loop sees seeded
collections.

Coverage:
  1. Generator: per-niche starter sets + unknown-niche fallback.
  2. Handle derivation (title -> URL-safe slug).
  3. Applier: empty input short-circuits.
  4. Applier: all-success path + recording.
  5. Applier: router_unavailable + per-collection failure recording.
  6. Applier: partial failure (one rejection doesn't block the
     other inserts).
  7. Applier: adapter raise captured.
  8. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.collection_seeder import (
    _slug,
    apply_starter_collections,
    generate_starter_collections,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# --- Slug ------------------------------------------------------


class TestSlug:

    def test_lowercase_with_hyphens(self):
        assert _slug("New Arrivals") == "new-arrivals"
        assert _slug("Gift Sets") == "gift-sets"

    def test_strips_outer_hyphens(self):
        assert _slug("  Hello  ") == "hello"

    def test_empty_falls_back(self):
        assert _slug("") == "collection"
        assert _slug("---") == "collection"


# --- Generator ------------------------------------------------


class TestGenerator:

    def test_beauty_set(self):
        specs = generate_starter_collections(niche="beauty")
        titles = [s["title"] for s in specs]
        assert "Skincare" in titles
        assert "Makeup" in titles
        assert "Gift Sets" in titles

    def test_fashion_includes_sale(self):
        specs = generate_starter_collections(niche="fashion")
        titles = [s["title"] for s in specs]
        assert "Sale" in titles
        assert "New Arrivals" in titles

    def test_unknown_niche_falls_back_to_general(self):
        specs = generate_starter_collections(
            niche="ufo_parts",
        )
        titles = [s["title"] for s in specs]
        assert "New Arrivals" in titles
        assert "Best Sellers" in titles

    def test_each_spec_has_required_fields(self):
        specs = generate_starter_collections(niche="tech")
        for s in specs:
            assert s["title"]
            assert s["handle"]
            assert s["description_html"].startswith("<p>")
            assert s["sort_order"] == "BEST_SELLING"

    def test_empty_niche_defaults_to_general(self):
        specs = generate_starter_collections(niche="")
        assert len(specs) >= 4


class TestExtendedNiches:
    """Niches added after the initial 6 (beauty/fashion/
    tech/home/food/general). Each niche must produce at
    least 4 collections with the canonical spec shape."""

    NICHES = ("pets", "fitness", "jewelry", "outdoor", "baby")

    def test_every_extended_niche_has_a_set(self):
        for niche in self.NICHES:
            specs = generate_starter_collections(niche=niche)
            assert len(specs) >= 4, niche

    def test_every_extended_niche_spec_is_well_shaped(self):
        for niche in self.NICHES:
            specs = generate_starter_collections(niche=niche)
            for s in specs:
                assert s["title"], niche
                assert s["handle"], niche
                assert s["description_html"].startswith("<p>")
                assert s["sort_order"] == "BEST_SELLING"

    def test_niche_specific_titles(self):
        pets = generate_starter_collections(niche="pets")
        assert "Dogs" in {s["title"] for s in pets}
        fitness = generate_starter_collections(
            niche="fitness",
        )
        assert "Supplements" in {
            s["title"] for s in fitness
        }
        jewelry = generate_starter_collections(
            niche="jewelry",
        )
        assert "Rings" in {s["title"] for s in jewelry}
        outdoor = generate_starter_collections(
            niche="outdoor",
        )
        assert "Camping + Hiking" in {
            s["title"] for s in outdoor
        }
        baby = generate_starter_collections(niche="baby")
        assert "Nursery" in {s["title"] for s in baby}


# --- Applier --------------------------------------------------


class TestApplierEmpty:

    def test_empty_list(self):
        out = apply_starter_collections([])
        assert out == {"applied_count": 0, "results": []}

    def test_non_list(self):
        out = apply_starter_collections(None)  # type: ignore[arg-type]
        assert out == {"applied_count": 0, "results": []}


class TestApplierSuccess:

    def test_all_collections_applied(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        with patch(
            "engines.store_setup.collection_seeder."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.collection_seeder."
            "record_writeback",
        ) as record_mock:
            specs = generate_starter_collections(niche="beauty")
            out = apply_starter_collections(specs)
        assert out["applied_count"] == 4
        assert all(r["ok"] for r in out["results"])
        # Pattern Z recorded once per collection
        assert record_mock.call_count == 4
        for call in record_mock.call_args_list:
            assert call.kwargs["success"] is True

    def test_passes_spec_through_to_adapter(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        with patch(
            "engines.store_setup.collection_seeder."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.collection_seeder."
            "record_writeback",
        ):
            apply_starter_collections([
                {"title": "Sale", "handle": "sale",
                 "description_html": "<p>x</p>",
                 "sort_order": "MANUAL"},
            ])
        call_args = router.execute.call_args.args
        # Spec was passed through unchanged
        spec_passed = call_args[1]
        assert spec_passed["title"] == "Sale"
        assert spec_passed["sort_order"] == "MANUAL"


class TestApplierFailures:

    def test_router_unavailable_records_all(self):
        with patch(
            "engines.store_setup.collection_seeder."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.collection_seeder."
            "record_writeback",
        ) as record_mock:
            out = apply_starter_collections([
                {"title": "A"}, {"title": "B"},
            ])
        assert out["applied_count"] == 0
        assert all(
            r["error"] == "router_unavailable"
            for r in out["results"]
        )
        assert record_mock.call_count == 2

    def test_partial_failure(self):
        def _by_title(cap, spec):
            if spec.get("title") == "B":
                return _fail("dup handle")
            return _ok()
        router = MagicMock()
        router.execute.side_effect = _by_title
        with patch(
            "engines.store_setup.collection_seeder."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.collection_seeder."
            "record_writeback",
        ):
            out = apply_starter_collections([
                {"title": "A"},
                {"title": "B"},
                {"title": "C"},
            ])
        assert out["applied_count"] == 2
        by_title = {
            r["title"]: r for r in out["results"]
        }
        assert by_title["A"]["ok"] is True
        assert by_title["B"]["ok"] is False
        assert "dup handle" in by_title["B"]["error"]
        assert by_title["C"]["ok"] is True

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        with patch(
            "engines.store_setup.collection_seeder."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.collection_seeder."
            "record_writeback",
        ):
            out = apply_starter_collections([{"title": "A"}])
        assert out["applied_count"] == 0
        assert "adapter_raise" in out["results"][0]["error"]
        assert "network" in out["results"][0]["error"]


# --- store_id propagation ------------------------------------


class TestStoreIdPropagation:

    def test_store_id_in_recorded_params(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        with patch(
            "engines.store_setup.collection_seeder."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.collection_seeder."
            "record_writeback",
        ) as record_mock:
            apply_starter_collections(
                [{"title": "Sale"}],
                store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
        assert params["title"] == "Sale"
