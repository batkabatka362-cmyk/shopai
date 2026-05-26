"""Tests for engines._niche_detector."""
from __future__ import annotations

from unittest.mock import MagicMock

from engines._niche_detector import (
    NicheDetection,
    detect_niche_from_products,
    suggest_niche_for_store,
    _count_keyword_hits,
    _extract_text_blob,
)


def _product(*, title="", product_type="", vendor="", tags=None):
    return {
        "title": title,
        "product_type": product_type,
        "vendor": vendor,
        "tags": tags if tags is not None else [],
    }


class TestExtractTextBlob:

    def test_combines_title_type_vendor_tags(self):
        p = _product(
            title="Red Lipstick",
            product_type="Cosmetic",
            vendor="BeautyCo",
            tags=["makeup", "matte"],
        )
        blob = _extract_text_blob(p)
        assert "red lipstick" in blob
        assert "cosmetic" in blob
        assert "beautyco" in blob
        assert "makeup" in blob
        assert "matte" in blob

    def test_tolerates_missing_fields(self):
        # Missing keys, None tags, non-string vendor
        p = {"title": "Phone Case"}
        blob = _extract_text_blob(p)
        assert "phone case" in blob

    def test_tags_string_or_list(self):
        # Shopify returns tags as comma-string sometimes
        p = _product(title="X", tags="beauty, makeup")
        blob = _extract_text_blob(p)
        assert "beauty" in blob
        assert "makeup" in blob


class TestCountKeywordHits:

    def test_word_boundary_single_token(self):
        # 'tech' should not match inside 'protechnical'
        assert _count_keyword_hits("protechnical gear", ["tech"]) == 0
        assert _count_keyword_hits("tech gadget", ["tech"]) == 1

    def test_phrase_match(self):
        assert _count_keyword_hits(
            "skin care routine", ["skin care"],
        ) == 1

    def test_hyphenated_phrase(self):
        assert _count_keyword_hits(
            "gluten-free snack", ["gluten-free"],
        ) == 1

    def test_multiple_keywords_one_blob(self):
        # 'skincare' AND 'serum' both count
        hits = _count_keyword_hits(
            "facial serum and skincare", ["skincare", "serum"],
        )
        assert hits == 2

    def test_no_match_returns_zero(self):
        assert _count_keyword_hits(
            "nothing here", ["beauty", "tech"],
        ) == 0


class TestDetectNicheFromProducts:

    def test_empty_list_returns_no_data(self):
        d = detect_niche_from_products([])
        assert d.suggested == "general"
        assert d.confidence == "no_data"
        assert d.products_analyzed == 0

    def test_none_returns_no_data(self):
        d = detect_niche_from_products(None)
        assert d.confidence == "no_data"

    def test_pure_beauty_catalog_high_confidence(self):
        products = [
            _product(title="Foundation", tags=["makeup"]),
            _product(title="Lipstick", tags=["cosmetics"]),
            _product(title="Serum", tags=["skincare"]),
            _product(title="Moisturizer", tags=["beauty"]),
        ]
        d = detect_niche_from_products(products)
        assert d.suggested == "beauty"
        assert d.confidence == "high"
        assert d.scores["beauty"] > d.scores["tech"]

    def test_pure_tech_catalog(self):
        products = [
            _product(title="Wireless Earbuds"),
            _product(title="Bluetooth Speaker"),
            _product(title="USB-C Cable"),
            _product(title="Phone Charger"),
        ]
        d = detect_niche_from_products(products)
        assert d.suggested == "tech"
        assert d.confidence in ("high", "medium")

    def test_mixed_catalog_lower_confidence(self):
        # Half beauty, half tech -- top niche only gets ~50%
        products = [
            _product(title="Lipstick", tags=["makeup"]),
            _product(title="Phone Charger", tags=["tech"]),
            _product(title="Bluetooth Headphones"),
            _product(title="Foundation", tags=["beauty"]),
        ]
        d = detect_niche_from_products(products)
        assert d.suggested in ("beauty", "tech")
        # Top ratio shouldn't be high (>=70%)
        assert d.top_score_ratio < 0.7

    def test_no_keyword_hits_no_data(self):
        # Products with no niche keywords at all
        products = [
            _product(title="Generic Item A"),
            _product(title="Whatever Object"),
        ]
        d = detect_niche_from_products(products)
        assert d.confidence == "no_data"
        assert d.total_matches == 0

    def test_actionable_property_high_medium_only(self):
        # actionable iff confidence ∈ {medium, high}
        assert NicheDetection(
            suggested="beauty", confidence="high",
        ).is_actionable
        assert NicheDetection(
            suggested="beauty", confidence="medium",
        ).is_actionable
        assert not NicheDetection(
            suggested="beauty", confidence="low",
        ).is_actionable
        assert not NicheDetection(
            suggested="general", confidence="no_data",
        ).is_actionable

    def test_deterministic_tie_breaker_is_alphabetical(self):
        # Build a tie where two niches both have score 1.
        # Use a single product matching exactly one beauty kw
        # and one tech kw. Tie -> beauty wins (b < t).
        products = [
            _product(title="lipstick tech accessory"),
        ]
        d = detect_niche_from_products(products)
        # Both beauty (lipstick) and tech (tech) match.
        # Sorted lexicographically -> beauty wins.
        assert d.scores["beauty"] >= 1
        assert d.scores["tech"] >= 1
        # On exact tie, alphabetical first wins
        if d.scores["beauty"] == d.scores["tech"]:
            assert d.suggested == "beauty"

    def test_products_analyzed_counts_dicts_only(self):
        products = [
            _product(title="Lipstick"),
            "not_a_dict",  # ignored
            _product(title="Serum"),
        ]
        d = detect_niche_from_products(products)
        assert d.products_analyzed == 2


class TestSuggestNicheForStore:

    def test_returns_none_when_store_missing(self):
        sm = MagicMock()
        sm.get_store.return_value = None
        result = suggest_niche_for_store("missing", store_manager=sm)
        assert result is None

    def test_returns_no_data_when_no_products(self):
        sm = MagicMock()
        sm.get_store.return_value = {"store_id": "s1"}
        sm.get_products.return_value = []
        result = suggest_niche_for_store("s1", store_manager=sm)
        assert result is not None
        assert result.confidence == "no_data"

    def test_returns_detection_when_products_match(self):
        sm = MagicMock()
        sm.get_store.return_value = {"store_id": "s1"}
        sm.get_products.return_value = [
            _product(title="Lipstick"),
            _product(title="Foundation"),
            _product(title="Serum"),
        ]
        result = suggest_niche_for_store("s1", store_manager=sm)
        assert result is not None
        assert result.suggested == "beauty"

    def test_returns_none_when_manager_raises(self):
        sm = MagicMock()
        sm.get_store.side_effect = Exception("boom")
        result = suggest_niche_for_store("s1", store_manager=sm)
        assert result is None
