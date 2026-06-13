"""Tests for engines.product_sourcer — W963-2."""
from __future__ import annotations

import pytest

from engines.product_sourcer import ProductSourcerEngine
from engines.product_sourcer.catalogs import (
    SUPPORTED_NICHES,
    catalog_summary,
    get_catalog,
)


# ── Catalog integrity ──────────────────────────────────────


class TestCatalogIntegrity:
    def test_all_supported_niches_have_candidates(self):
        for niche in SUPPORTED_NICHES:
            rows = get_catalog(niche)
            assert len(rows) >= 20, (
                f"{niche} catalog too thin "
                f"(got {len(rows)})"
            )

    def test_unknown_niche_returns_empty(self):
        assert get_catalog("cars") == []
        assert get_catalog("") == []
        assert get_catalog(None) == []  # type: ignore[arg-type]

    def test_catalog_summary_lists_all_niches(self):
        summary = catalog_summary()
        for n in SUPPORTED_NICHES:
            assert n in summary
            assert summary[n] >= 20

    def test_each_candidate_has_required_fields(self):
        for niche in SUPPORTED_NICHES:
            for c in get_catalog(niche):
                assert c.name
                assert c.category
                assert c.description
                assert c.price_min >= 0
                assert c.price_max >= c.price_min
                assert isinstance(c.tags, list)

    def test_catalog_returns_fresh_list_copy(self):
        """Mutating the returned list MUST NOT bleed into
        future calls — guards against test-pollution of the
        module-level catalog."""
        first = get_catalog("beauty")
        before = len(first)
        first.pop()
        first.pop()
        second = get_catalog("beauty")
        assert len(second) == before


# ── Pattern Q envelope ─────────────────────────────────────


class TestPatternQEnvelope:
    def test_empty_input_returns_success(self):
        result = ProductSourcerEngine().run({})
        assert set(result.keys()) == {
            "status", "data", "meta", "error",
        }
        assert result["status"] == "success"
        assert result["error"] is None
        assert result["meta"]["engine"] == "product_sourcer"

    def test_none_input_returns_success(self):
        result = ProductSourcerEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_input_returns_error(self):
        result = ProductSourcerEngine().run("not a dict")
        assert result["status"] == "error"
        assert result["data"] is None

    def test_fail_upstream_short_circuits(self):
        result = ProductSourcerEngine().run({
            "status": "fail", "error": "upstream broke",
        })
        assert result["status"] == "error"


# ── Engine behaviour ──────────────────────────────────────


class TestEngineHappyPath:
    def test_beauty_default_returns_20(self):
        result = ProductSourcerEngine().run({
            "data": {"niche": "beauty"},
        })
        assert result["status"] == "success"
        assert result["data"]["count_returned"] == 20
        assert len(result["data"]["candidates"]) == 20

    def test_count_5_returns_5(self):
        result = ProductSourcerEngine().run({
            "data": {"niche": "fashion", "count": 5},
        })
        assert result["data"]["count_returned"] == 5

    def test_count_exceeds_catalog_returns_full(self):
        result = ProductSourcerEngine().run({
            "data": {"niche": "tech", "count": 999},
        })
        assert result["data"]["count_returned"] <= 100  # cap

    def test_each_candidate_has_suggested_price(self):
        result = ProductSourcerEngine().run({
            "data": {"niche": "home", "count": 3},
        })
        for c in result["data"]["candidates"]:
            assert "suggested_price" in c
            assert c["suggested_price"] > 0
            assert c["suggested_price"] >= c["price_min"]
            # suggested price should be near the midpoint
            mid = (c["price_min"] + c["price_max"]) / 2
            assert abs(c["suggested_price"] - mid) < 2.5


class TestEngineNiche:
    def test_unsupported_niche_returns_error(self):
        result = ProductSourcerEngine().run({
            "data": {"niche": "cars"},
        })
        assert result["status"] == "error"
        assert "unsupported niche" in (result["error"] or "")

    def test_uppercase_niche_normalised(self):
        result = ProductSourcerEngine().run({
            "data": {"niche": "BEAUTY"},
        })
        assert result["status"] == "success"
        assert result["data"]["niche"] == "beauty"

    def test_non_string_niche_returns_error(self):
        result = ProductSourcerEngine().run({
            "data": {"niche": 123},
        })
        assert result["status"] == "error"
        assert "string" in (result["error"] or "")


class TestEngineCount:
    def test_non_int_count_returns_error(self):
        result = ProductSourcerEngine().run({
            "data": {"niche": "tech", "count": "many"},
        })
        assert result["status"] == "error"

    def test_zero_count_returns_error(self):
        result = ProductSourcerEngine().run({
            "data": {"niche": "tech", "count": 0},
        })
        assert result["status"] == "error"
        assert ">= 1" in (result["error"] or "")


class TestEnginePriceFilter:
    def test_low_price_max_filters_catalog(self):
        result = ProductSourcerEngine().run({
            "data": {
                "niche": "tech", "count": 20,
                "price_max": 15.0,
            },
        })
        assert result["status"] == "success"
        for c in result["data"]["candidates"]:
            assert c["price_min"] <= 15.0

    def test_filter_yielding_zero_returns_empty_success(self):
        result = ProductSourcerEngine().run({
            "data": {
                "niche": "fashion", "count": 5,
                "price_max": 1.0,
            },
        })
        assert result["status"] == "success"
        assert result["data"]["count_returned"] == 0
        assert "$1.00" in result["data"]["next_action"]

    def test_non_numeric_price_max_returns_error(self):
        result = ProductSourcerEngine().run({
            "data": {
                "niche": "fashion",
                "price_max": "cheap",
            },
        })
        assert result["status"] == "error"


# ── Empty input shape ──────────────────────────────────────


class TestEmptyInput:
    def test_empty_niche_returns_catalog_summary(self):
        result = ProductSourcerEngine().run({})
        assert result["status"] == "success"
        next_action = result["data"]["next_action"]
        for n in SUPPORTED_NICHES:
            assert n in next_action

    def test_empty_string_niche_treated_as_summary(self):
        result = ProductSourcerEngine().run({
            "data": {"niche": ""},
        })
        assert result["status"] == "success"
        assert result["data"]["count_returned"] == 0


class TestImageQueryBuilder:
    """W963-169: _build_image_query strips size/quantity
    suffixes + appends a niche-theme word so Pexels search
    returns niche-appropriate photos."""

    def test_strips_ml_suffix(self):
        from engines.product_sourcer.draft_creator import (
            _build_image_query,
        )
        q = _build_image_query(
            {"name": "Rose Hip Hydrating Toner 200ml"},
            "beauty",
        )
        assert "200ml" not in q
        assert "skincare" in q
        assert "rose hip" in q

    def test_strips_pack_suffix(self):
        from engines.product_sourcer.draft_creator import (
            _build_image_query,
        )
        q = _build_image_query(
            {"name": "Matcha Antioxidant Face Mask (5-pack)"},
            "beauty",
        )
        assert "5" not in q
        assert "pack" not in q
        assert "matcha" in q

    def test_appends_niche_theme(self):
        from engines.product_sourcer.draft_creator import (
            _build_image_query,
        )
        q = _build_image_query(
            {"name": "Bamboo Cutting Board"}, "home",
        )
        assert "home" in q

    def test_empty_name_falls_back_to_niche(self):
        from engines.product_sourcer.draft_creator import (
            _build_image_query,
        )
        assert _build_image_query(
            {}, "beauty",
        ) == "beauty"

    def test_query_capped_at_6_words(self):
        from engines.product_sourcer.draft_creator import (
            _build_image_query,
        )
        q = _build_image_query(
            {
                "name": (
                    "Super Premium Triple Action Vitamin "
                    "C Brightening Serum Plus"
                ),
            },
            "beauty",
        )
        assert len(q.split()) <= 6

    def test_word_boundary_preserves_compound_words(self):
        """W963-172: unit-strip regex needs \\b so '200gram'
        / '5-package' / '10ozonic' don't get mangled."""
        from engines.product_sourcer.draft_creator import (
            _build_image_query,
        )
        # '200gram' must NOT lose 'gram' chars
        q = _build_image_query(
            {"name": "Vitamin C 200gram Cream"},
            "beauty",
        )
        assert "gram" in q  # 200gram preserved
        assert "cream" in q
        # '5-package' must NOT lose 'age'
        q2 = _build_image_query(
            {"name": "Tea 5-package"}, "beauty",
        )
        assert "package" in q2

    def test_theme_always_survives_6_word_cap(self):
        """W963-172: niche theme word must appear in the
        final query even when name has 6+ words."""
        from engines.product_sourcer.draft_creator import (
            _build_image_query,
        )
        q = _build_image_query(
            {
                "name": (
                    "Hydrating Daily Face Brightening "
                    "Vitamin C Serum"
                ),
            },
            "beauty",
        )
        assert "skincare" in q  # theme survived
        assert len(q.split()) <= 6
