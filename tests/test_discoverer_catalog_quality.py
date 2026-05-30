"""Tests for catalog_quality discoverer (Wave 824)."""
from __future__ import annotations

from unittest.mock import patch

from core.automation.discoverers.catalog_quality import (
    _classify_product,
    _limit,
    discover_catalog_quality,
)
from core.automation.payload_discoverer import (
    discover, has_discoverer,
)


class TestRegistryWireup:

    def test_registered_after_import(self):
        assert has_discoverer("catalog_quality")

    def test_dispatch_via_registry(self):
        with patch(
            "core.automation.discoverers.catalog_quality."
            "_fetch_products",
            return_value=[],
        ):
            r = discover("catalog_quality")
        assert r.ok
        assert r.payload == []
        assert r.source == "shopify_products"


class TestClassifyProduct:

    def test_needs_images_when_zero(self):
        assert _classify_product({
            "id": "p1",
            "images": [],
        }) == "shopai-quality-needs-images"

    def test_thin_description_under_80_chars(self):
        assert _classify_product({
            "id": "p1",
            "images": [{"src": "x"}],
            "description": "short",
        }) == "shopai-quality-thin-description"

    def test_no_variants_with_default_only(self):
        assert _classify_product({
            "id": "p1",
            "images": [{"src": "x"}],
            "description": "a" * 200,
            "variants": [{"title": "Default Title"}],
        }) == "shopai-quality-no-variants"

    def test_draft_flagged_for_review(self):
        assert _classify_product({
            "id": "p1",
            "images": [{"src": "x"}],
            "description": "a" * 200,
            "variants": [{"title": "Red / Large"}],
            "status": "draft",
        }) == "shopai-quality-flagged-review"

    def test_validated_when_all_pass(self):
        assert _classify_product({
            "id": "p1",
            "images": [{"src": "x"}],
            "description": "a" * 200,
            "variants": [{"title": "Red / Large"}],
            "status": "active",
        }) == "shopai-quality-validated"

    def test_non_dict_returns_none(self):
        assert _classify_product("not a dict") is None


class TestDiscover:

    def test_empty_products_empty_payload(self):
        with patch(
            "core.automation.discoverers.catalog_quality."
            "_fetch_products",
            return_value=[],
        ):
            r = discover_catalog_quality()
        assert r.ok
        assert r.payload == []

    def test_products_become_payload(self):
        products = [
            {
                "id": "gid://shopify/Product/1",
                "images": [],
            },
            {
                "id": "gid://shopify/Product/2",
                "images": [{"src": "x"}],
                "description": "a" * 200,
                "variants": [{"title": "Red"}],
                "status": "active",
            },
        ]
        with patch(
            "core.automation.discoverers.catalog_quality."
            "_fetch_products",
            return_value=products,
        ):
            r = discover_catalog_quality()
        assert r.ok
        assert len(r.payload) == 2
        tags = sorted(p["tag"] for p in r.payload)
        assert tags == [
            "shopai-quality-needs-images",
            "shopai-quality-validated",
        ]
        for p in r.payload:
            assert p["action"] == "tag_quality"

    def test_skips_product_with_no_id(self):
        with patch(
            "core.automation.discoverers.catalog_quality."
            "_fetch_products",
            return_value=[{
                "id": "",
                "images": [],
            }],
        ):
            r = discover_catalog_quality()
        assert r.payload == []

    def test_fetch_raise_captured(self):
        def explode():
            raise RuntimeError("network down")
        with patch(
            "core.automation.discoverers.catalog_quality."
            "_fetch_products",
            side_effect=explode,
        ):
            r = discover_catalog_quality()
        assert not r.ok
        assert "network down" in r.error


class TestLimit:

    def test_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_CATALOG_QUALITY_DISCOVER_LIMIT",
            raising=False,
        )
        assert _limit() == 100

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_CATALOG_QUALITY_DISCOVER_LIMIT", "25",
        )
        assert _limit() == 25

    def test_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_CATALOG_QUALITY_DISCOVER_LIMIT", "abc",
        )
        assert _limit() == 100

    def test_clamps_minimum(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_CATALOG_QUALITY_DISCOVER_LIMIT", "0",
        )
        assert _limit() == 1
