"""Unit tests for core/adapters/shopify_admin/.

Covers:
  * ShopifyAdminClient — env constructor, URL build, retry
    on 429/5xx, error envelope parsing, GraphQL error
    surfacing
  * Discounts — price rule CRUD, discount code CRUD, one-call
    percentage helper, negative-value quirk, lookup → None
    on 404, expiry calculation
  * Inventory — locations, list_levels (required args),
    set (idempotent), adjust, connect, item get + set_cost
  * DraftOrders — list by status, get, create (variant_id +
    custom line item), update, delete, send_invoice, complete
    (both payment_pending modes)
"""
from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
    ShopifyAdminMisconfigured, DEFAULT_API_VERSION,
)
from core.adapters.shopify_admin.discounts import Discounts
from core.adapters.shopify_admin.inventory import Inventory
from core.adapters.shopify_admin.draft_orders import DraftOrders


# ── Client ───────────────────────────────────────────────


class TestClientConstruction:
    def test_from_env_ok(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_URL", "deguar.myshopify.com",
        )
        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_KEY", "shpat_xxx",
        )
        client = ShopifyAdminClient.from_env()
        assert client.url == "deguar.myshopify.com"
        assert client.token == "shpat_xxx"
        assert client.api_version == DEFAULT_API_VERSION

    def test_from_env_token_alias(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_URL", "x.myshopify.com",
        )
        monkeypatch.delenv(
            "SHOPAI_SHOPIFY_KEY", raising=False,
        )
        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_TOKEN", "alt_token",
        )
        client = ShopifyAdminClient.from_env()
        assert client.token == "alt_token"

    def test_missing_env_raises(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_SHOPIFY_URL", raising=False,
        )
        monkeypatch.delenv(
            "SHOPAI_SHOPIFY_KEY", raising=False,
        )
        monkeypatch.delenv(
            "SHOPAI_SHOPIFY_TOKEN", raising=False,
        )
        with pytest.raises(ShopifyAdminMisconfigured):
            ShopifyAdminClient.from_env()


class TestClientURL:
    def test_url_build(self):
        c = ShopifyAdminClient(
            url="x.myshopify.com", token="t",
        )
        assert c._url("products.json").endswith(
            f"/admin/api/{DEFAULT_API_VERSION}/products.json",
        )

    def test_leading_slash_normalised(self):
        c = ShopifyAdminClient(
            url="x.myshopify.com", token="t",
        )
        url = c._url("/products/123.json")
        assert url.endswith("/products/123.json")
        assert "admin/api" in url


class _FakeResponse:
    def __init__(self, body: str = "{}", status: int = 200):
        self._body = body.encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestClientSend:
    def _mk_client(self):
        return ShopifyAdminClient(
            url="x.myshopify.com", token="shpat_xxx",
        )

    def test_get_parses_json(self):
        client = self._mk_client()
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(
                '{"products": [{"id": 1}]}',
            ),
        ):
            result = client.get("products.json")
        assert result == {"products": [{"id": 1}]}

    def test_empty_body_returns_empty_dict(self):
        client = self._mk_client()
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(""),
        ):
            result = client.get("x.json")
        assert result == {}

    def test_non_json_body_raises(self):
        client = self._mk_client()
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse("<html>oops</html>"),
        ):
            with pytest.raises(ShopifyAdminError):
                client.get("x.json")

    def test_404_raises_with_status(self):
        client = self._mk_client()

        def boom(*a, **kw):
            err = urllib.error.HTTPError(
                "u", 404, "Not Found", None, None,
            )
            err.read = lambda: b'{"error":"not found"}'
            raise err
        with patch("urllib.request.urlopen", side_effect=boom):
            with pytest.raises(ShopifyAdminError) as exc:
                client.get("missing.json")
        assert exc.value.status == 404

    def test_429_retries(self):
        client = ShopifyAdminClient(
            url="x.myshopify.com", token="t", retries=2,
        )
        call_count = {"n": 0}

        def flaky(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                err = urllib.error.HTTPError(
                    "u", 429, "Too Many", {}, None,
                )
                err.headers = MagicMock()
                err.headers.get.return_value = "0.01"
                err.read = lambda: b""
                raise err
            return _FakeResponse('{"ok": true}')

        with patch("urllib.request.urlopen", side_effect=flaky):
            result = client.get("x.json")
        assert result == {"ok": True}
        assert call_count["n"] == 2

    def test_503_retries(self):
        client = ShopifyAdminClient(
            url="x.myshopify.com", token="t", retries=2,
        )
        call_count = {"n": 0}

        def flaky(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                err = urllib.error.HTTPError(
                    "u", 503, "Unavailable", {}, None,
                )
                err.read = lambda: b""
                raise err
            return _FakeResponse('{}')

        with patch(
            "urllib.request.urlopen", side_effect=flaky,
        ), patch("time.sleep"):
            client.get("x.json")
        assert call_count["n"] == 2


class TestClientGraphQL:
    def test_top_level_errors_raise(self):
        client = ShopifyAdminClient(
            url="x.myshopify.com", token="t",
        )
        body = json.dumps({
            "errors": [{"message": "access denied"}],
        })
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(body),
        ):
            with pytest.raises(
                ShopifyAdminError, match="access denied",
            ):
                client.graphql("{ shop { id } }")

    def test_clean_response_returned(self):
        client = ShopifyAdminClient(
            url="x.myshopify.com", token="t",
        )
        body = json.dumps({
            "data": {"shop": {"id": "gid://..."}},
        })
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(body),
        ):
            result = client.graphql("{ shop { id } }")
        assert result["data"]["shop"]["id"]


# ── Discounts ───────────────────────────────────────────


def _fake_client():
    """Build a fake client whose methods are patchable."""
    c = MagicMock(spec=ShopifyAdminClient)
    return c


class TestDiscountsPriceRules:
    def test_list_happy_path(self):
        c = _fake_client()
        c.get.return_value = {"price_rules": [
            {"id": 1, "title": "A"},
            {"id": 2, "title": "B"},
        ]}
        rules = Discounts.list_price_rules(c, limit=10)
        c.get.assert_called_once()
        assert len(rules) == 2

    def test_create_percentage_negates_value(self):
        """Shopify wants NEGATIVE values for discounts. Verify
        the helper negates a positive input."""
        c = _fake_client()
        c.post.return_value = {"price_rule": {"id": 99}}
        Discounts.create_price_rule(
            c, title="SUMMER", value_pct=15,
        )
        args = c.post.call_args
        body = args[0][1]
        assert body["price_rule"]["value"] == "-15.0"
        assert (
            body["price_rule"]["value_type"] == "percentage"
        )

    def test_create_fixed_amount(self):
        c = _fake_client()
        c.post.return_value = {"price_rule": {"id": 99}}
        Discounts.create_price_rule(
            c, title="$5 off", value_fixed_usd=5.00,
        )
        body = c.post.call_args[0][1]
        assert body["price_rule"]["value"] == "-5.0"
        assert (
            body["price_rule"]["value_type"] == "fixed_amount"
        )

    def test_create_requires_exactly_one_value(self):
        c = _fake_client()
        with pytest.raises(ValueError, match="exactly one"):
            Discounts.create_price_rule(c, title="X")
        with pytest.raises(ValueError, match="only one"):
            Discounts.create_price_rule(
                c, title="X",
                value_pct=10, value_fixed_usd=5,
            )

    def test_update_partial(self):
        c = _fake_client()
        c.put.return_value = {"price_rule": {"id": 42}}
        Discounts.update_price_rule(
            c, 42, fields={"ends_at": "2026-12-31T23:59:59Z"},
        )
        args = c.put.call_args[0]
        assert "42" in args[0]
        assert (
            args[1]["price_rule"]["ends_at"]
            == "2026-12-31T23:59:59Z"
        )

    def test_update_empty_fields_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Discounts.update_price_rule(c, 1, fields={})

    def test_delete(self):
        c = _fake_client()
        Discounts.delete_price_rule(c, 42)
        c.delete.assert_called_once()


class TestDiscountsCodes:
    def test_create_uppercases_code(self):
        c = _fake_client()
        c.post.return_value = {"discount_code": {"code": "SUMMER20"}}
        Discounts.create_discount_code(
            c, 1, code="summer20",
        )
        body = c.post.call_args[0][1]
        assert body["discount_code"]["code"] == "SUMMER20"

    def test_create_empty_code_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Discounts.create_discount_code(c, 1, code="")
        with pytest.raises(ValueError):
            Discounts.create_discount_code(c, 1, code="   ")

    def test_lookup_404_returns_none(self):
        c = _fake_client()
        c.get.side_effect = ShopifyAdminError(
            "not found", status=404,
        )
        assert Discounts.lookup_discount_code(c, "GONE") is None

    def test_lookup_empty_code_returns_none(self):
        c = _fake_client()
        assert Discounts.lookup_discount_code(c, "") is None


class TestDiscountsOneCall:
    def test_percentage_helper_creates_both(self):
        c = _fake_client()
        c.post.side_effect = [
            {"price_rule": {"id": 77, "title": "x"}},
            {"discount_code": {"id": 88, "code": "VIP20"}},
        ]
        result = Discounts.create_percentage_code(
            c, code="VIP20", value_pct=20,
            once_per_customer=True, usage_limit=100,
        )
        # Two REST calls
        assert c.post.call_count == 2
        # First body: price rule
        rule_body = c.post.call_args_list[0][0][1]
        assert rule_body["price_rule"]["value"] == "-20.0"
        assert (
            rule_body["price_rule"]["once_per_customer"] is True
        )
        assert rule_body["price_rule"]["usage_limit"] == 100
        # Second body: discount code attached to rule 77
        code_path = c.post.call_args_list[1][0][0]
        assert "/77/" in code_path
        # Result contains both
        assert result["price_rule"]["id"] == 77
        assert result["discount_code"]["code"] == "VIP20"

    def test_expires_in_days_sets_ends_at(self):
        c = _fake_client()
        c.post.side_effect = [
            {"price_rule": {"id": 1}},
            {"discount_code": {"id": 2, "code": "X"}},
        ]
        Discounts.create_percentage_code(
            c, code="X", value_pct=10,
            expires_in_days=7,
        )
        rule_body = c.post.call_args_list[0][0][1]
        assert "ends_at" in rule_body["price_rule"]


# ── Inventory ───────────────────────────────────────────


class TestLocations:
    def test_list_locations(self):
        c = _fake_client()
        c.get.return_value = {"locations": [
            {"id": 1, "name": "Main", "active": True},
            {"id": 2, "name": "Old", "active": False},
        ]}
        locs = Inventory.list_locations(c)
        assert len(locs) == 2

    def test_primary_location_skips_inactive(self):
        c = _fake_client()
        c.get.return_value = {"locations": [
            {"id": 2, "name": "Old", "active": False},
            {"id": 10, "name": "Main", "active": True},
        ]}
        assert Inventory.primary_location_id(c) == 10

    def test_primary_falls_back_when_all_inactive(self):
        c = _fake_client()
        c.get.return_value = {"locations": [
            {"id": 5, "active": False},
        ]}
        assert Inventory.primary_location_id(c) == 5

    def test_primary_none_when_no_locations(self):
        c = _fake_client()
        c.get.return_value = {"locations": []}
        assert Inventory.primary_location_id(c) is None


class TestLevels:
    def test_list_requires_filter(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Inventory.list_levels(c)

    def test_list_by_item(self):
        c = _fake_client()
        c.get.return_value = {"inventory_levels": [
            {"inventory_item_id": 1, "available": 10},
        ]}
        levels = Inventory.list_levels(
            c, inventory_item_ids=[1, 2],
        )
        assert len(levels) == 1
        params = c.get.call_args[1]["params"]
        assert params["inventory_item_ids"] == "1,2"

    def test_set_level_idempotent_shape(self):
        c = _fake_client()
        c.post.return_value = {
            "inventory_level": {"available": 42},
        }
        Inventory.set_level(
            c, inventory_item_id=100,
            location_id=200, available=42,
        )
        body = c.post.call_args[0][1]
        assert body == {
            "inventory_item_id": 100,
            "location_id": 200,
            "available": 42,
        }

    def test_set_level_coerces_string_to_int(self):
        c = _fake_client()
        c.post.return_value = {
            "inventory_level": {"available": 5},
        }
        Inventory.set_level(
            c, inventory_item_id="100",
            location_id="200", available="5",
        )
        body = c.post.call_args[0][1]
        assert body["available"] == 5

    def test_set_level_invalid_available_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Inventory.set_level(
                c, inventory_item_id=1,
                location_id=1, available="not a number",
            )

    def test_adjust_level(self):
        c = _fake_client()
        c.post.return_value = {
            "inventory_level": {"available": 15},
        }
        Inventory.adjust_level(
            c, inventory_item_id=100,
            location_id=200, available_adjustment=5,
        )
        body = c.post.call_args[0][1]
        assert body["available_adjustment"] == 5

    def test_connect_level(self):
        c = _fake_client()
        c.post.return_value = {
            "inventory_level": {"inventory_item_id": 1},
        }
        Inventory.connect_level(
            c, inventory_item_id=1, location_id=2,
        )
        assert "connect" in c.post.call_args[0][0]


class TestInventoryItems:
    def test_get_item(self):
        c = _fake_client()
        c.get.return_value = {"inventory_item": {
            "id": 1, "cost": "10.00", "sku": "ABC",
        }}
        item = Inventory.get_item(c, 1)
        assert item["cost"] == "10.00"

    def test_set_cost_formatted(self):
        c = _fake_client()
        c.put.return_value = {"inventory_item": {"cost": "12.50"}}
        Inventory.set_item_cost(c, 1, cost_usd=12.5)
        body = c.put.call_args[0][1]
        assert body["inventory_item"]["cost"] == "12.50"


# ── DraftOrders ─────────────────────────────────────────


class TestDraftOrdersCRUD:
    def test_list_default_open(self):
        c = _fake_client()
        c.get.return_value = {"draft_orders": [
            {"id": 1, "status": "open"},
        ]}
        DraftOrders.list_drafts(c)
        params = c.get.call_args[1]["params"]
        assert params["status"] == "open"

    def test_get_by_id(self):
        c = _fake_client()
        c.get.return_value = {"draft_order": {"id": 42}}
        d = DraftOrders.get(c, 42)
        assert d["id"] == 42

    def test_create_with_variant_id(self):
        c = _fake_client()
        c.post.return_value = {"draft_order": {"id": 99}}
        DraftOrders.create(
            c, line_items=[
                {"variant_id": 55, "quantity": 2},
            ],
            customer_email="JANE@X.COM",
        )
        body = c.post.call_args[0][1]
        assert body["draft_order"]["line_items"] == [
            {"variant_id": 55, "quantity": 2},
        ]
        # Email normalised
        assert body["draft_order"]["email"] == "jane@x.com"

    def test_create_custom_line_item(self):
        c = _fake_client()
        c.post.return_value = {"draft_order": {"id": 99}}
        DraftOrders.create(
            c, line_items=[
                {"title": "Custom X", "price": 12.50,
                 "quantity": 1},
            ],
        )
        body = c.post.call_args[0][1]
        item = body["draft_order"]["line_items"][0]
        assert item["title"] == "Custom X"
        assert item["price"] == "12.50"

    def test_create_empty_line_items_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError, match="line_items"):
            DraftOrders.create(c, line_items=[])

    def test_create_invalid_line_item_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError, match="line_item"):
            DraftOrders.create(
                c, line_items=[{"no_variant_no_title": True}],
            )

    def test_create_with_applied_discount(self):
        c = _fake_client()
        c.post.return_value = {"draft_order": {"id": 1}}
        DraftOrders.create(
            c, line_items=[{"variant_id": 1, "quantity": 1}],
            applied_discount={
                "title": "VIP", "value_type": "percentage",
                "value": "20.0",
            },
        )
        body = c.post.call_args[0][1]
        assert body["draft_order"]["applied_discount"][
            "title"
        ] == "VIP"

    def test_update(self):
        c = _fake_client()
        c.put.return_value = {"draft_order": {"id": 42}}
        DraftOrders.update(c, 42, fields={"note": "new note"})
        body = c.put.call_args[0][1]
        assert body["draft_order"]["note"] == "new note"

    def test_delete(self):
        c = _fake_client()
        DraftOrders.delete(c, 42)
        c.delete.assert_called_once()


class TestDraftOrdersLifecycle:
    def test_send_invoice(self):
        c = _fake_client()
        c.post.return_value = {
            "draft_order_invoice": {"to": "jane@x.com"},
        }
        DraftOrders.send_invoice(
            c, 42, to="jane@x.com",
            subject="Your quote is ready",
        )
        path = c.post.call_args[0][0]
        assert "/send_invoice" in path
        body = c.post.call_args[0][1]
        assert body["draft_order_invoice"][
            "to"
        ] == "jane@x.com"
        assert body["draft_order_invoice"][
            "subject"
        ] == "Your quote is ready"

    def test_complete_payment_pending(self):
        c = _fake_client()
        c.put.return_value = {
            "draft_order": {"id": 42, "order_id": 555},
        }
        DraftOrders.complete(c, 42)
        # Verify payment_pending=true in params
        call = c.put.call_args
        assert call[1]["params"]["payment_pending"] == "true"

    def test_complete_paid(self):
        c = _fake_client()
        c.put.return_value = {
            "draft_order": {"id": 42, "order_id": 555},
        }
        DraftOrders.complete(
            c, 42, payment_pending=False,
        )
        call = c.put.call_args
        assert call[1]["params"]["payment_pending"] == "false"
