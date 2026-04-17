"""Tests for sourcing / dropshipping-supplier adapters.

Real HTTP is forbidden — every test patches the adapter's
``_http_request`` (or ``_cj_request``) to return canned vendor
payloads. Covers:

  * Metadata (category, capabilities, priority, requires_key)
  * Two-credential configuration detection (email + password)
  * Access-token fetch + caching + refresh on 401
  * Request shapes for each capability
  * Response normalisation → canonical product / order records
  * Status-vocabulary mapping (CJ state → ready/processing/etc.)
  * Validation (missing fields, bad types, empty lists)
  * Bootstrap registration
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterValidationError,
    Capability,
    get_config,
    get_registry,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)
from core.adapters.errors import AdapterAuthError


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "CJ_DROPSHIPPING_EMAIL", "CJ_DROPSHIPPING_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _cfg(monkeypatch, **kv):
    for k, v in kv.items():
        monkeypatch.setenv(k, v)
    get_config().reload()


def _cj(monkeypatch):
    from core.adapters.sourcing.cj_dropshipping import CJDropshippingAdapter
    _cfg(
        monkeypatch,
        CJ_DROPSHIPPING_EMAIL="ops@shopai.test",
        CJ_DROPSHIPPING_PASSWORD="s3cret",
    )
    a = CJDropshippingAdapter()
    # Pre-seed the token cache so tests don't need to stub the
    # login exchange unless they're specifically testing it.
    a._token = "cached-token"
    a._token_expires_at = 10 ** 12
    return a


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestCJMetadata:
    def test_metadata(self):
        from core.adapters.sourcing.cj_dropshipping import CJDropshippingAdapter
        a = CJDropshippingAdapter()
        assert a.name == "cj_dropshipping"
        assert a.category == AdapterCategory.SOURCING
        assert a.priority == 90
        assert a.requires_key is True
        assert a.capabilities == {
            Capability.SOURCING_SEARCH_PRODUCTS,
            Capability.SOURCING_GET_PRODUCT,
            Capability.SOURCING_CREATE_ORDER,
            Capability.SOURCING_GET_ORDER_STATUS,
        }

    def test_unconfigured_without_email(self):
        from core.adapters.sourcing.cj_dropshipping import CJDropshippingAdapter
        assert not CJDropshippingAdapter().is_configured()

    def test_unconfigured_with_only_email(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import CJDropshippingAdapter
        _cfg(monkeypatch, CJ_DROPSHIPPING_EMAIL="a@b.c")
        assert not CJDropshippingAdapter().is_configured()

    def test_unconfigured_with_only_password(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import CJDropshippingAdapter
        _cfg(monkeypatch, CJ_DROPSHIPPING_PASSWORD="p")
        assert not CJDropshippingAdapter().is_configured()

    def test_configured_with_both(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import CJDropshippingAdapter
        _cfg(
            monkeypatch,
            CJ_DROPSHIPPING_EMAIL="a@b.c",
            CJ_DROPSHIPPING_PASSWORD="pw",
        )
        assert CJDropshippingAdapter().is_configured()

    def test_describe_lists_sourcing_capabilities(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import CJDropshippingAdapter
        _cfg(
            monkeypatch,
            CJ_DROPSHIPPING_EMAIL="a@b.c", CJ_DROPSHIPPING_PASSWORD="pw",
        )
        d = CJDropshippingAdapter().describe()
        assert d["category"] == "sourcing"
        assert "sourcing_search_products" in d["capabilities"]


# ---------------------------------------------------------------------------
# Token handling
# ---------------------------------------------------------------------------


class TestCJToken:
    def test_token_fetch_populates_cache(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import CJDropshippingAdapter
        _cfg(
            monkeypatch,
            CJ_DROPSHIPPING_EMAIL="a@b.c", CJ_DROPSHIPPING_PASSWORD="pw",
        )
        a = CJDropshippingAdapter()
        with patch.object(
            a, "_http_request",
            return_value={"code": 200, "result": True,
                          "data": {"accessToken": "tok-xyz"}},
        ) as m:
            tok = a._get_token()
        assert tok == "tok-xyz"
        assert a._token == "tok-xyz"
        # Subsequent calls reuse cached token (no second HTTP call).
        a._get_token()
        assert m.call_count == 1

    def test_token_force_refresh_ignores_cache(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import CJDropshippingAdapter
        _cfg(
            monkeypatch,
            CJ_DROPSHIPPING_EMAIL="a@b.c", CJ_DROPSHIPPING_PASSWORD="pw",
        )
        a = CJDropshippingAdapter()
        a._token = "old"
        a._token_expires_at = 10 ** 12
        with patch.object(
            a, "_http_request",
            return_value={"code": 200, "data": {"accessToken": "new"}},
        ) as m:
            tok = a._get_token(force_refresh=True)
        assert tok == "new"
        assert m.call_count == 1

    def test_token_missing_raises_auth_error(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import CJDropshippingAdapter
        _cfg(
            monkeypatch,
            CJ_DROPSHIPPING_EMAIL="a@b.c", CJ_DROPSHIPPING_PASSWORD="pw",
        )
        a = CJDropshippingAdapter()
        with patch.object(
            a, "_http_request",
            return_value={"code": 401, "message": "bad credentials"},
        ):
            with pytest.raises(AdapterAuthError):
                a._get_token()

    def test_auth_headers_carry_cj_access_token(self, monkeypatch):
        a = _cj(monkeypatch)
        headers = a._auth_headers()
        assert headers["CJ-Access-Token"] == "cached-token"
        assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# Search products
# ---------------------------------------------------------------------------


class TestCJSearchProducts:
    def test_search_normalises_records(self, monkeypatch):
        a = _cj(monkeypatch)
        raw = {
            "code": 200,
            "result": True,
            "data": {
                "list": [
                    {
                        "pid": "P-1",
                        "productName": "Silent Posture Corrector",
                        "productImage": "https://cdn.cj/a.jpg;https://cdn.cj/b.jpg",
                        "sellPrice": "12.50",
                        "categoryName": "Health",
                        "countryCode": "CN",
                        "productWeight": 150,
                        "productUrl": "https://cjdropshipping.com/product/P-1",
                    },
                    {
                        "pid": "P-2",
                        "productName": "Other",
                        "productImage": ["https://cdn.cj/c.jpg"],
                        "priceRange": "$8.99--$15.50",
                    },
                ],
            },
        }
        with patch.object(a, "_http_request", return_value=raw) as m:
            out = a.execute(
                Capability.SOURCING_SEARCH_PRODUCTS,
                {"query": "posture", "limit": 5, "page": 2},
            )
        kwargs = m.call_args[1]
        assert kwargs["params"]["keyWords"] == "posture"
        assert kwargs["params"]["pageSize"] == 5
        assert kwargs["params"]["pageNum"] == 2
        # Response
        assert out.ok is True
        assert out.data["total"] == 2
        p1 = out.data["products"][0]
        assert p1["sourcing_id"] == "P-1"
        assert p1["title"] == "Silent Posture Corrector"
        assert p1["source"] == "cj_dropshipping"
        assert p1["cost_usd"] == 12.5
        assert p1["images"] == [
            "https://cdn.cj/a.jpg", "https://cdn.cj/b.jpg",
        ]
        assert p1["origin_country"] == "CN"
        assert p1["weight_grams"] == 150
        assert p1["raw_url"] == "https://cjdropshipping.com/product/P-1"
        # Second product: price_range fallback
        p2 = out.data["products"][1]
        assert p2["cost_usd"] == 8.99
        assert p2["images"] == ["https://cdn.cj/c.jpg"]

    def test_missing_query_fails_validation(self, monkeypatch):
        a = _cj(monkeypatch)
        res = a.execute(Capability.SOURCING_SEARCH_PRODUCTS, {})
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_limit_out_of_range_fails_validation(self, monkeypatch):
        a = _cj(monkeypatch)
        res = a.execute(
            Capability.SOURCING_SEARCH_PRODUCTS,
            {"query": "x", "limit": 9999},
        )
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_cj_logical_failure_propagates(self, monkeypatch):
        a = _cj(monkeypatch)
        with patch.object(
            a, "_http_request",
            return_value={"code": 1003, "result": False, "message": "oops"},
        ):
            res = a.execute(
                Capability.SOURCING_SEARCH_PRODUCTS,
                {"query": "x"},
            )
        assert not res.ok
        assert "oops" in str(res.error)


# ---------------------------------------------------------------------------
# Get product
# ---------------------------------------------------------------------------


class TestCJGetProduct:
    def test_get_product_normalises_variants(self, monkeypatch):
        a = _cj(monkeypatch)
        raw = {
            "code": 200,
            "data": {
                "pid": "P-42",
                "productName": "Widget",
                "description": "<p>Nice <b>widget</b></p>",
                "categoryName": "Gadgets",
                "sellPrice": "14.00",
                "suggestSellPrice": "29.99",
                "productImage": "https://cdn.cj/1.jpg;https://cdn.cj/2.jpg",
                "sourceFrom": "CN",
                "productWeight": "200",
                "minShippingDays": 7,
                "maxShippingDays": 15,
                "productUrl": "https://cjdropshipping.com/product/P-42",
                "variants": [
                    {
                        "vid": "V-1",
                        "variantSku": "SKU-RED",
                        "variantKey": "Color:Red-Size:XL",
                        "variantSellPrice": "14.00",
                        "variantStock": 100,
                    },
                    {
                        "vid": "V-2",
                        "variantSku": "SKU-BLUE",
                        "variantKey": "Color:Blue-Size:M",
                        "variantSellPrice": "13.50",
                        "variantStock": 50,
                    },
                ],
            },
        }
        with patch.object(a, "_http_request", return_value=raw) as m:
            out = a.execute(
                Capability.SOURCING_GET_PRODUCT, {"sourcing_id": "P-42"},
            )
        # URL + pid param
        kwargs = m.call_args[1]
        assert kwargs["params"]["pid"] == "P-42"
        # Response
        prod = out.data["product"]
        assert prod["sourcing_id"] == "P-42"
        assert prod["title"] == "Widget"
        # Strips HTML
        assert "<" not in prod["description"]
        assert "widget" in prod["description"].lower()
        assert prod["cost_usd"] == 14.0
        assert prod["suggested_price_usd"] == 29.99
        assert prod["shipping_days_min"] == 7
        assert prod["shipping_days_max"] == 15
        assert prod["origin_country"] == "CN"
        assert prod["weight_grams"] == 200
        assert len(prod["variants"]) == 2
        v1 = prod["variants"][0]
        assert v1["variant_id"] == "V-1"
        assert v1["sku"] == "SKU-RED"
        assert v1["cost_usd"] == 14.0
        assert v1["stock"] == 100
        assert v1["attributes"] == {"color": "Red", "size": "XL"}

    def test_accepts_product_id_alias(self, monkeypatch):
        a = _cj(monkeypatch)
        with patch.object(
            a, "_http_request",
            return_value={"code": 200, "data": {"pid": "P-9"}},
        ):
            out = a.execute(
                Capability.SOURCING_GET_PRODUCT, {"product_id": "P-9"},
            )
        assert out.ok
        assert out.data["product"]["sourcing_id"] == "P-9"

    def test_missing_id_fails_validation(self, monkeypatch):
        a = _cj(monkeypatch)
        res = a.execute(Capability.SOURCING_GET_PRODUCT, {})
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_uses_variant_cost_when_top_level_zero(self, monkeypatch):
        a = _cj(monkeypatch)
        with patch.object(
            a, "_http_request",
            return_value={
                "code": 200,
                "data": {
                    "pid": "P-7",
                    "productName": "Thing",
                    "variants": [
                        {"vid": "V-a", "variantSellPrice": "9.99"},
                        {"vid": "V-b", "variantSellPrice": "7.50"},
                    ],
                },
            },
        ):
            out = a.execute(
                Capability.SOURCING_GET_PRODUCT, {"sourcing_id": "P-7"},
            )
        # Lowest variant cost surfaces as product cost.
        assert out.data["product"]["cost_usd"] == 7.5


# ---------------------------------------------------------------------------
# Create order
# ---------------------------------------------------------------------------


class TestCJCreateOrder:
    _SHIPPING = {
        "name":     "Batka Customer",
        "address1": "123 Market St",
        "city":     "San Francisco",
        "state":    "CA",
        "zip":      "94103",
        "country":  "US",
        "phone":    "+15555551234",
        "shipping_method": "CJPacket Ordinary",
    }

    def test_create_order_builds_cj_body(self, monkeypatch):
        a = _cj(monkeypatch)
        with patch.object(
            a, "_http_request",
            return_value={
                "code": 200,
                "result": True,
                "data": {"orderId": "CJ-ORD-777"},
            },
        ) as m:
            out = a.execute(Capability.SOURCING_CREATE_ORDER, {
                "external_order_id": "shopify-1001",
                "items": [
                    {
                        "sourcing_id": "P-1",
                        "variant_id":  "V-1",
                        "quantity":    2,
                        "cost_usd":    12.5,
                    },
                ],
                "shipping": dict(self._SHIPPING),
            })
        kwargs = m.call_args[1]
        body = kwargs["body"]
        assert body["orderNumber"] == "shopify-1001"
        assert body["shippingCountryCode"] == "US"
        assert body["shippingZip"] == "94103"
        assert body["shippingCustomerName"] == "Batka Customer"
        assert body["logisticName"] == "CJPacket Ordinary"
        assert body["products"] == [{
            "vid": "V-1", "quantity": 2,
            "shippingName": "CJPacket Ordinary",
        }]
        # Response
        order = out.data["order"]
        assert order["order_id"] == "CJ-ORD-777"
        assert order["status"] == "pending"
        assert order["items"][0]["variant_id"] == "V-1"
        assert order["items"][0]["quantity"] == 2
        # cost_usd = 12.5 × 2
        assert order["cost_usd"] == 25.0

    def test_missing_items_fails_validation(self, monkeypatch):
        a = _cj(monkeypatch)
        res = a.execute(Capability.SOURCING_CREATE_ORDER, {
            "items": [], "shipping": dict(self._SHIPPING),
        })
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_missing_shipping_fails_validation(self, monkeypatch):
        a = _cj(monkeypatch)
        res = a.execute(Capability.SOURCING_CREATE_ORDER, {
            "items": [{"variant_id": "V-1", "quantity": 1}],
        })
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_shipping_missing_country_fails(self, monkeypatch):
        a = _cj(monkeypatch)
        ship = {k: v for k, v in self._SHIPPING.items() if k != "country"}
        res = a.execute(Capability.SOURCING_CREATE_ORDER, {
            "items": [{"variant_id": "V-1", "quantity": 1}],
            "shipping": ship,
        })
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_item_missing_quantity_fails(self, monkeypatch):
        a = _cj(monkeypatch)
        res = a.execute(Capability.SOURCING_CREATE_ORDER, {
            "items": [{"variant_id": "V-1", "quantity": 0}],
            "shipping": dict(self._SHIPPING),
        })
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_item_missing_variant_id_fails(self, monkeypatch):
        a = _cj(monkeypatch)
        res = a.execute(Capability.SOURCING_CREATE_ORDER, {
            "items": [{"quantity": 1}],
            "shipping": dict(self._SHIPPING),
        })
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)


# ---------------------------------------------------------------------------
# Order status
# ---------------------------------------------------------------------------


class TestCJOrderStatus:
    def test_get_order_status_maps_state(self, monkeypatch):
        a = _cj(monkeypatch)
        with patch.object(
            a, "_http_request",
            return_value={
                "code": 200,
                "data": {
                    "orderId": "CJ-1",
                    "orderStatus": "Shipped",
                    "trackNumber": "TRK-9",
                    "logisticName": "CJPacket",
                    "orderAmount": "25.00",
                    "shippedTime": "2026-04-01T08:00:00Z",
                    "products": [
                        {
                            "pid": "P-1", "vid": "V-1", "quantity": 2,
                            "sellPrice": "12.50",
                        },
                    ],
                },
            },
        ):
            out = a.execute(
                Capability.SOURCING_GET_ORDER_STATUS, {"order_id": "CJ-1"},
            )
        order = out.data["order"]
        assert order["order_id"] == "CJ-1"
        assert order["status"] == "shipped"
        assert order["tracking_number"] == "TRK-9"
        assert order["carrier"] == "CJPacket"
        assert order["cost_usd"] == 25.0
        assert order["shipped_at"] == "2026-04-01T08:00:00Z"
        assert len(order["items"]) == 1
        assert order["items"][0]["quantity"] == 2

    def test_status_map_unknown_falls_back_to_processing(self, monkeypatch):
        a = _cj(monkeypatch)
        with patch.object(
            a, "_http_request",
            return_value={
                "code": 200,
                "data": {"orderId": "CJ-2", "orderStatus": "quantum"},
            },
        ):
            out = a.execute(
                Capability.SOURCING_GET_ORDER_STATUS, {"order_id": "CJ-2"},
            )
        assert out.data["order"]["status"] == "processing"

    def test_status_map_delivered(self, monkeypatch):
        a = _cj(monkeypatch)
        with patch.object(
            a, "_http_request",
            return_value={
                "code": 200,
                "data": {"orderId": "CJ-3", "orderStatus": "Delivered"},
            },
        ):
            out = a.execute(
                Capability.SOURCING_GET_ORDER_STATUS, {"order_id": "CJ-3"},
            )
        assert out.data["order"]["status"] == "delivered"

    def test_status_map_cancelled(self, monkeypatch):
        a = _cj(monkeypatch)
        with patch.object(
            a, "_http_request",
            return_value={
                "code": 200,
                "data": {"orderId": "CJ-4", "orderStatus": "Canceled"},
            },
        ):
            out = a.execute(
                Capability.SOURCING_GET_ORDER_STATUS, {"order_id": "CJ-4"},
            )
        assert out.data["order"]["status"] == "cancelled"

    def test_missing_order_id_fails_validation(self, monkeypatch):
        a = _cj(monkeypatch)
        res = a.execute(Capability.SOURCING_GET_ORDER_STATUS, {})
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


class TestNormalisation:
    def test_product_fills_missing_fields(self, monkeypatch):
        a = _cj(monkeypatch)
        out = a._normalise_product({"sourcing_id": "X"})
        for key in (
            "sourcing_id", "source", "title", "description", "category",
            "cost_usd", "suggested_price_usd", "currency", "images",
            "variants", "shipping_days_min", "shipping_days_max",
            "origin_country", "weight_grams", "raw_url",
        ):
            assert key in out
        assert out["source"] == "cj_dropshipping"
        assert out["currency"] == "USD"
        assert out["images"] == []
        assert out["variants"] == []

    def test_order_fills_missing_fields(self, monkeypatch):
        a = _cj(monkeypatch)
        out = a._normalise_order({"order_id": "O"})
        for key in (
            "order_id", "source", "status", "tracking_number",
            "tracking_url", "carrier", "cost_usd", "currency", "items",
            "shipped_at", "delivered_at", "raw_payload",
        ):
            assert key in out
        assert out["status"] == "pending"
        assert out["items"] == []
        assert out["currency"] == "USD"

    def test_non_dict_inputs_coerce_safely(self, monkeypatch):
        a = _cj(monkeypatch)
        out = a._normalise_product({
            "sourcing_id": "X",
            "cost_usd":    "not-a-number",
            "weight_grams": "heavy",
            "images":      None,
            "variants":    None,
        })
        assert out["cost_usd"] == 0.0
        assert out["weight_grams"] == 0
        assert out["images"] == []
        assert out["variants"] == []


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


class TestBootstrap:
    def test_register_all_registers_cj(self, monkeypatch):
        from core.adapters.sourcing.bootstrap import register_all
        status = register_all()
        assert "cj_dropshipping" in status
        assert status["cj_dropshipping"] is False  # no creds

    def test_register_all_reports_configured_when_creds_set(self, monkeypatch):
        _cfg(
            monkeypatch,
            CJ_DROPSHIPPING_EMAIL="a@b.c", CJ_DROPSHIPPING_PASSWORD="pw",
        )
        from core.adapters.sourcing.bootstrap import register_all
        status = register_all()
        assert status["cj_dropshipping"] is True

    def test_registry_has_sourcing_category(self, monkeypatch):
        _cfg(
            monkeypatch,
            CJ_DROPSHIPPING_EMAIL="a@b.c", CJ_DROPSHIPPING_PASSWORD="pw",
        )
        from core.adapters.sourcing.bootstrap import register_all
        register_all()
        reg = get_registry()
        names = [a.name for a in reg.find_by_category("sourcing")]
        assert "cj_dropshipping" in names
