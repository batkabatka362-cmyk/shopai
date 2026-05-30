"""Tests for product_seo discoverer (Wave 828)."""
from __future__ import annotations

from unittest.mock import patch

from core.automation.discoverers.product_seo import (
    _limit,
    _propose_for,
    _strip_html,
    discover_product_seo,
)
from core.automation.payload_discoverer import (
    discover, has_discoverer,
)


class TestRegistryWireup:

    def test_registered_after_import(self):
        assert has_discoverer("product_seo")

    def test_dispatch_via_registry(self):
        with patch(
            "core.automation.discoverers.product_seo."
            "_fetch_products",
            return_value=[],
        ):
            r = discover("product_seo")
        assert r.ok
        assert r.source == "shopify_products"


class TestPropose:

    def test_both_missing_yields_two_rows(self):
        rows = _propose_for({
            "id": "p1",
            "title": "Widget XL",
            "description": "Very nice widget for daily use.",
        })
        fields = sorted(r["field"] for r in rows)
        assert fields == ["meta_description", "meta_title"]
        for r in rows:
            assert r["action"] == "update_seo"
            assert r["product_id"] == "p1"

    def test_title_present_only_description_proposed(self):
        rows = _propose_for({
            "id": "p1",
            "title": "Widget XL",
            "description": (
                "Very nice widget for daily use. " * 10
            ),
            "seo": {"title": "Widget XL — Best Buy"},
        })
        assert len(rows) == 1
        assert rows[0]["field"] == "meta_description"

    def test_description_present_only_title_proposed(self):
        rows = _propose_for({
            "id": "p1",
            "title": "Widget XL",
            "description": "x" * 200,
            "seo": {
                "description": "a" * 100,
            },
        })
        assert len(rows) == 1
        assert rows[0]["field"] == "meta_title"

    def test_both_present_no_rows(self):
        rows = _propose_for({
            "id": "p1",
            "title": "Widget XL",
            "description": "x" * 200,
            "seo": {
                "title": "Widget XL",
                "description": "a" * 100,
            },
        })
        assert rows == []

    def test_missing_id_yields_nothing(self):
        rows = _propose_for({"title": "x"})
        assert rows == []

    def test_non_dict_yields_nothing(self):
        assert _propose_for("not a dict") == []

    def test_no_body_falls_back_to_title(self):
        rows = _propose_for({
            "id": "p1",
            "title": "Just A Title",
        })
        # Both meta_title + meta_description rows generated;
        # description falls back to title.
        descs = [
            r for r in rows
            if r["field"] == "meta_description"
        ]
        assert descs
        assert "Just A Title" in descs[0]["new_value"]

    def test_proposed_value_clamped(self):
        rows = _propose_for({
            "id": "p1",
            "title": "x" * 500,
            "description": "y" * 500,
        })
        for r in rows:
            assert len(r["new_value"]) <= 320


class TestDiscover:

    def test_no_products_empty_payload(self):
        with patch(
            "core.automation.discoverers.product_seo."
            "_fetch_products",
            return_value=[],
        ):
            r = discover_product_seo()
        assert r.ok
        assert r.payload == []

    def test_products_become_payload(self):
        products = [
            {
                "id": "gid://shopify/Product/1",
                "title": "Alpha",
                "description": "Alpha is a great item " * 8,
            },
            {
                "id": "gid://shopify/Product/2",
                "title": "Beta",
                "description": "y" * 200,
                "seo": {
                    "title": "Beta — Pre-set",
                    "description": "Pre-set " + "x" * 100,
                },
            },
        ]
        with patch(
            "core.automation.discoverers.product_seo."
            "_fetch_products",
            return_value=products,
        ):
            r = discover_product_seo()
        # Alpha: 2 events (both missing). Beta: 0.
        assert len(r.payload) == 2
        for row in r.payload:
            assert row["product_id"] == (
                "gid://shopify/Product/1"
            )

    def test_fetch_raise_captured(self):
        def explode():
            raise RuntimeError("oops")
        with patch(
            "core.automation.discoverers.product_seo."
            "_fetch_products",
            side_effect=explode,
        ):
            r = discover_product_seo()
        assert not r.ok
        assert "oops" in r.error


class TestStripHtml:

    def test_p_tags_become_spaces(self):
        assert (
            _strip_html("<p>foo</p><p>bar</p>")
            == "foo bar"
        )

    def test_br_tags_become_spaces(self):
        assert _strip_html("a<br>b<br/>c<br />d") == "a b c d"


class TestLimit:

    def test_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_PRODUCT_SEO_DISCOVER_LIMIT",
            raising=False,
        )
        assert _limit() == 100

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_PRODUCT_SEO_DISCOVER_LIMIT", "10",
        )
        assert _limit() == 10
