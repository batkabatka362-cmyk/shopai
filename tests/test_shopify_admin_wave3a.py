"""Tests for Wave 3a of shopify_admin: orders + products."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)
from core.adapters.shopify_admin.orders import (
    Orders, OrderRisks,
)
from core.adapters.shopify_admin.products import (
    Products, Variants, ProductImages, ProductMetafields,
)


def _fake_client():
    return MagicMock(spec=ShopifyAdminClient)


# ── Orders ───────────────────────────────────────────────


class TestOrdersRead:
    def test_list_basic(self):
        c = _fake_client()
        c.get.return_value = {"orders": [
            {"id": 1}, {"id": 2},
        ]}
        out = Orders.list_orders(c, limit=100)
        assert len(out) == 2
        params = c.get.call_args[1]["params"]
        assert params["limit"] == 100
        assert params["status"] == "any"

    def test_list_with_filters(self):
        c = _fake_client()
        c.get.return_value = {"orders": []}
        Orders.list_orders(
            c,
            status="closed",
            financial_status="paid",
            fulfillment_status="fulfilled",
            since_id=100,
            created_at_min="2026-04-01T00:00:00Z",
        )
        params = c.get.call_args[1]["params"]
        assert params["financial_status"] == "paid"
        assert params["fulfillment_status"] == "fulfilled"
        assert params["since_id"] == "100"
        assert params["created_at_min"].startswith("2026")

    def test_get(self):
        c = _fake_client()
        c.get.return_value = {"order": {"id": 42}}
        assert Orders.get(c, 42)["id"] == 42

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            Orders.get(c, 42)

    def test_count(self):
        c = _fake_client()
        c.get.return_value = {"count": 123}
        assert Orders.count(c) == 123


class TestOrdersCancel:
    def test_cancel_happy_path(self):
        c = _fake_client()
        c.post.return_value = {"order": {"id": 42}}
        Orders.cancel(
            c, 42, reason="customer",
            restock=True, email_customer=True,
        )
        body = c.post.call_args[0][1]
        assert body["reason"] == "customer"
        assert body["restock"] is True
        assert body["email"] is True

    def test_invalid_reason_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError, match="reason"):
            Orders.cancel(c, 42, reason="nope")

    def test_close(self):
        c = _fake_client()
        c.post.return_value = {"order": {"id": 42}}
        Orders.close(c, 42)
        assert "close.json" in c.post.call_args[0][0]

    def test_open(self):
        c = _fake_client()
        c.post.return_value = {"order": {"id": 42}}
        Orders.open(c, 42)
        assert "open.json" in c.post.call_args[0][0]


class TestOrdersUpdate:
    def test_update_injects_id(self):
        c = _fake_client()
        c.put.return_value = {"order": {"id": 42}}
        Orders.update(c, 42, fields={"note": "gift-wrap"})
        body = c.put.call_args[0][1]
        assert body["order"]["id"] == 42
        assert body["order"]["note"] == "gift-wrap"

    def test_update_empty_fields_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Orders.update(c, 42, fields={})


class TestOrderTags:
    def test_add_tags_merges(self):
        c = _fake_client()
        c.get.return_value = {"order": {
            "id": 42, "tags": "rush, express",
        }}
        c.put.return_value = {"order": {"id": 42}}
        Orders.add_tags(c, 42, ["vip", "gift"])
        body = c.put.call_args[0][1]
        tags = set(body["order"]["tags"].split(", "))
        assert tags == {"rush", "express", "vip", "gift"}

    def test_remove_tags_case_insensitive(self):
        c = _fake_client()
        c.get.return_value = {"order": {
            "id": 42, "tags": "RUSH, vip, gift",
        }}
        c.put.return_value = {"order": {"id": 42}}
        Orders.remove_tags(c, 42, ["rush"])
        body = c.put.call_args[0][1]
        tags = set(body["order"]["tags"].split(", "))
        assert "RUSH" not in tags
        assert tags == {"gift", "vip"}


class TestOrderRisks:
    def test_list(self):
        c = _fake_client()
        c.get.return_value = {"risks": [
            {"id": 1, "recommendation": "accept"},
        ]}
        assert len(OrderRisks.list_risks(c, 42)) == 1

    def test_create_happy_path(self):
        c = _fake_client()
        c.post.return_value = {"risk": {"id": 1}}
        OrderRisks.create(
            c, 42,
            message="High risk: mismatched IP",
            recommendation="investigate",
            score=0.85,
            source="Fraud Protect",
            cause_cancel=False,
        )
        body = c.post.call_args[0][1]
        r = body["risk"]
        assert r["message"] == "High risk: mismatched IP"
        assert r["recommendation"] == "investigate"
        assert r["score"] == 0.85
        assert r["cause_cancel"] is False

    def test_create_missing_fields_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            OrderRisks.create(
                c, 42, message="", recommendation="cancel",
            )
        with pytest.raises(ValueError):
            OrderRisks.create(
                c, 42, message="x", recommendation="",
            )

    def test_delete(self):
        c = _fake_client()
        OrderRisks.delete(c, 42, 7)
        c.delete.assert_called_once()


# ── Products ─────────────────────────────────────────────


class TestProductsRead:
    def test_list_with_filters(self):
        c = _fake_client()
        c.get.return_value = {"products": [{"id": 1}]}
        Products.list_products(
            c,
            limit=250,
            status="active",
            handle="galaxy-projector",
            vendor="Deguar",
            product_type="Lamp",
        )
        params = c.get.call_args[1]["params"]
        assert params["status"] == "active"
        assert params["handle"] == "galaxy-projector"
        assert params["vendor"] == "Deguar"
        assert params["product_type"] == "Lamp"

    def test_get(self):
        c = _fake_client()
        c.get.return_value = {"product": {"id": 42}}
        assert Products.get(c, 42)["id"] == 42

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            Products.get(c, 42)

    def test_count(self):
        c = _fake_client()
        c.get.return_value = {"count": 99}
        assert Products.count(c, status="active") == 99


class TestProductsWrite:
    def test_create_requires_title(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Products.create(c, title="")

    def test_create_defaults_to_draft(self):
        c = _fake_client()
        c.post.return_value = {"product": {"id": 1}}
        Products.create(c, title="Galaxy Projector")
        body = c.post.call_args[0][1]
        assert body["product"]["status"] == "draft"

    def test_create_with_variants_and_tags(self):
        c = _fake_client()
        c.post.return_value = {"product": {"id": 1}}
        Products.create(
            c, title="X",
            tags=["cozy", "night-light"],
            variants=[{
                "price": "29.99", "sku": "X-S",
                "option1": "Small",
            }],
            images=[{"src": "https://x/1.jpg"}],
            status="active",
        )
        body = c.post.call_args[0][1]
        assert body["product"]["tags"] == "cozy, night-light"
        assert len(body["product"]["variants"]) == 1
        assert body["product"]["status"] == "active"

    def test_update_injects_id(self):
        c = _fake_client()
        c.put.return_value = {"product": {"id": 42}}
        Products.update(c, 42, fields={"vendor": "Deguar"})
        body = c.put.call_args[0][1]
        assert body["product"]["id"] == 42
        assert body["product"]["vendor"] == "Deguar"

    def test_update_empty_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Products.update(c, 42, fields={})

    def test_delete(self):
        c = _fake_client()
        Products.delete(c, 42)
        c.delete.assert_called_once()


class TestProductStatusHelpers:
    def test_publish_sets_active(self):
        c = _fake_client()
        c.get.return_value = {"product": {"id": 42}}
        c.put.return_value = {"product": {"id": 42}}
        Products.publish(c, 42)
        body = c.put.call_args[0][1]
        assert body["product"]["status"] == "active"
        assert body["product"]["published"] is True

    def test_unpublish_sets_draft(self):
        c = _fake_client()
        c.put.return_value = {"product": {"id": 42}}
        Products.unpublish(c, 42)
        body = c.put.call_args[0][1]
        assert body["product"]["status"] == "draft"
        assert body["product"]["published"] is False

    def test_archive(self):
        c = _fake_client()
        c.put.return_value = {"product": {"id": 42}}
        Products.archive(c, 42)
        body = c.put.call_args[0][1]
        assert body["product"]["status"] == "archived"


class TestProductTags:
    def test_add_tags_merges(self):
        c = _fake_client()
        c.get.return_value = {"product": {
            "id": 42, "tags": "cozy, bedroom",
        }}
        c.put.return_value = {"product": {"id": 42}}
        Products.add_tags(c, 42, ["spa", "sleep"])
        body = c.put.call_args[0][1]
        tags = set(body["product"]["tags"].split(", "))
        assert tags == {"cozy", "bedroom", "spa", "sleep"}

    def test_remove_tags_case_insensitive(self):
        c = _fake_client()
        c.get.return_value = {"product": {
            "id": 42, "tags": "COZY, bedroom",
        }}
        c.put.return_value = {"product": {"id": 42}}
        Products.remove_tags(c, 42, ["cozy"])
        body = c.put.call_args[0][1]
        tags = set(body["product"]["tags"].split(", "))
        assert tags == {"bedroom"}


# ── Variants ─────────────────────────────────────────────


class TestVariants:
    def test_list(self):
        c = _fake_client()
        c.get.return_value = {"variants": [{"id": 1}]}
        assert len(Variants.list_variants(c, 42)) == 1

    def test_get(self):
        c = _fake_client()
        c.get.return_value = {"variant": {"id": 77}}
        assert Variants.get(c, 77)["id"] == 77

    def test_create_minimal(self):
        c = _fake_client()
        c.post.return_value = {"variant": {"id": 1}}
        Variants.create(c, 42, price=29.99)
        body = c.post.call_args[0][1]
        assert body["variant"]["price"] == "29.99"
        assert (
            body["variant"]["inventory_management"]
            == "shopify"
        )

    def test_create_with_all_options(self):
        c = _fake_client()
        c.post.return_value = {"variant": {"id": 1}}
        Variants.create(
            c, 42,
            price="19.99", sku="X-M",
            option1="Medium", option2="Blue",
            inventory_quantity=50,
            compare_at_price=39.99,
            weight=0.5, weight_unit="kg",
        )
        body = c.post.call_args[0][1]
        v = body["variant"]
        assert v["sku"] == "X-M"
        assert v["option1"] == "Medium"
        assert v["inventory_quantity"] == 50
        assert v["compare_at_price"] == "39.99"
        assert v["weight"] == 0.5

    def test_update_injects_id(self):
        c = _fake_client()
        c.put.return_value = {"variant": {"id": 77}}
        Variants.update(c, 77, fields={"sku": "NEW"})
        body = c.put.call_args[0][1]
        assert body["variant"]["id"] == 77
        assert body["variant"]["sku"] == "NEW"

    def test_update_empty_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Variants.update(c, 77, fields={})

    def test_delete_uses_product_path(self):
        c = _fake_client()
        Variants.delete(c, 42, 77)
        path = c.delete.call_args[0][0]
        assert "products/42/variants/77" in path

    def test_set_price_idempotent_shape(self):
        c = _fake_client()
        c.put.return_value = {"variant": {"id": 77}}
        Variants.set_price(c, 77, 24.99,
                           compare_at_price=34.99)
        body = c.put.call_args[0][1]
        assert body["variant"]["price"] == "24.99"
        assert body["variant"]["compare_at_price"] == "34.99"


# ── ProductImages ────────────────────────────────────────


class TestProductImages:
    def test_list(self):
        c = _fake_client()
        c.get.return_value = {"images": [{"id": 1}]}
        assert len(ProductImages.list_images(c, 42)) == 1

    def test_create_requires_src(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            ProductImages.create(c, 42, src="")

    def test_create_with_variant_ids(self):
        c = _fake_client()
        c.post.return_value = {"image": {"id": 1}}
        ProductImages.create(
            c, 42, src="https://x/a.jpg",
            alt="Galaxy projector front",
            position=1,
            variant_ids=[100, 200],
        )
        body = c.post.call_args[0][1]
        img = body["image"]
        assert img["src"] == "https://x/a.jpg"
        assert img["alt"] == "Galaxy projector front"
        assert img["position"] == 1
        assert img["variant_ids"] == [100, 200]

    def test_update(self):
        c = _fake_client()
        c.put.return_value = {"image": {"id": 1}}
        ProductImages.update(
            c, 42, 1, fields={"alt": "Updated caption"},
        )
        body = c.put.call_args[0][1]
        assert body["image"]["id"] == 1
        assert body["image"]["alt"] == "Updated caption"

    def test_delete(self):
        c = _fake_client()
        ProductImages.delete(c, 42, 1)
        c.delete.assert_called_once()


# ── ProductMetafields ────────────────────────────────────


class TestProductMetafields:
    def test_list_by_namespace(self):
        c = _fake_client()
        c.get.return_value = {"metafields": [{"id": 1}]}
        ProductMetafields.list_metafields(
            c, 42, namespace="shopai",
        )
        params = c.get.call_args[1]["params"]
        assert params["namespace"] == "shopai"

    def test_create_string_value(self):
        c = _fake_client()
        c.post.return_value = {"metafield": {"id": 1}}
        ProductMetafields.create(
            c, 42,
            namespace="shopai", key="warranty",
            value="1 year",
        )
        body = c.post.call_args[0][1]
        assert body["metafield"]["value"] == "1 year"
        assert (
            body["metafield"]["type"]
            == "single_line_text_field"
        )

    def test_create_json_value(self):
        c = _fake_client()
        c.post.return_value = {"metafield": {"id": 1}}
        ProductMetafields.create(
            c, 42,
            namespace="shopai", key="schema",
            value={"type": "Product", "name": "X"},
            value_type="json",
        )
        body = c.post.call_args[0][1]
        # Dict serialised to JSON string
        import json
        parsed = json.loads(body["metafield"]["value"])
        assert parsed["type"] == "Product"

    def test_create_requires_namespace_and_key(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            ProductMetafields.create(
                c, 42, namespace="", key="x", value="v",
            )
        with pytest.raises(ValueError):
            ProductMetafields.create(
                c, 42, namespace="x", key="", value="v",
            )

    def test_update_json(self):
        c = _fake_client()
        c.put.return_value = {"metafield": {"id": 1}}
        ProductMetafields.update(
            c, 42, 1, value={"a": 1},
        )
        body = c.put.call_args[0][1]
        import json
        parsed = json.loads(body["metafield"]["value"])
        assert parsed == {"a": 1}

    def test_delete(self):
        c = _fake_client()
        ProductMetafields.delete(c, 42, 1)
        c.delete.assert_called_once()
