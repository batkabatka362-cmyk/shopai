"""Unit tests for AutoDSAdapter.

Real HTTP is forbidden — every test patches
``adapter._http_request`` to return canned AutoDS payloads.
Mirrors tests/test_sourcing_adapters.py (CJ) so the two
adapters stay behaviour-compatible from the caller's view.

Covers:
  * Metadata (name, priority=80, capabilities, requires_key)
  * Config detection (AUTODS_API_KEY length threshold)
  * Response normalisation for each capability:
      - search → list of products
      - get → single product
      - create_order → ack record
      - get_order_status → status record
  * AutoDS-specific envelope edge cases (error at 200,
    bare-list response, dict response)
  * Validation failures raise the right typed error
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
from core.adapters.errors import AdapterError


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in ("AUTODS_API_KEY",):
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


def _autods(monkeypatch):
    from core.adapters.sourcing.autods import AutoDSAdapter
    _cfg(
        monkeypatch,
        AUTODS_API_KEY="a" * 40,  # min 20 char check in is_configured
    )
    return AutoDSAdapter()


# ── Metadata ─────────────────────────────────────────────


class TestAutoDSMetadata:
    def test_metadata(self):
        from core.adapters.sourcing.autods import AutoDSAdapter
        a = AutoDSAdapter()
        assert a.name == "autods"
        assert a.category == AdapterCategory.SOURCING
        assert a.priority == 80
        assert a.requires_key is True
        assert a.capabilities == {
            Capability.SOURCING_SEARCH_PRODUCTS,
            Capability.SOURCING_GET_PRODUCT,
            Capability.SOURCING_CREATE_ORDER,
            Capability.SOURCING_GET_ORDER_STATUS,
        }

    def test_unconfigured_without_key(self):
        from core.adapters.sourcing.autods import AutoDSAdapter
        assert not AutoDSAdapter().is_configured()

    def test_unconfigured_with_short_key(self, monkeypatch):
        """AutoDS tokens are 40+ chars. A 5-char value is
        either a typo or a placeholder — reject."""
        from core.adapters.sourcing.autods import AutoDSAdapter
        _cfg(monkeypatch, AUTODS_API_KEY="abc")
        assert not AutoDSAdapter().is_configured()

    def test_configured_with_real_token(self, monkeypatch):
        from core.adapters.sourcing.autods import AutoDSAdapter
        _cfg(monkeypatch, AUTODS_API_KEY="a" * 40)
        assert AutoDSAdapter().is_configured()

    def test_describe_lists_sourcing_capabilities(
        self, monkeypatch,
    ):
        _cfg(monkeypatch, AUTODS_API_KEY="a" * 40)
        from core.adapters.sourcing.autods import AutoDSAdapter
        d = AutoDSAdapter().describe()
        assert d["category"] == "sourcing"
        assert "sourcing_search_products" in d["capabilities"]


# ── HTTP envelope ────────────────────────────────────────


class TestEnvelope:
    def test_non_object_response_raises(self, monkeypatch):
        a = _autods(monkeypatch)
        with patch.object(
            a, "_http_request", return_value="not a dict",
        ):
            with pytest.raises(AdapterError):
                a._autods_request("GET", "/products/search")

    def test_bare_list_wrapped_as_list_key(self, monkeypatch):
        a = _autods(monkeypatch)
        with patch.object(
            a, "_http_request",
            return_value=[{"id": "p1"}, {"id": "p2"}],
        ):
            out = a._autods_request("GET", "/x")
        assert out == {"list": [{"id": "p1"}, {"id": "p2"}]}

    def test_200_with_error_field_raises(self, monkeypatch):
        """AutoDS sometimes returns HTTP 200 with an ``error``
        field (plan quota, etc.). Surface as typed error rather
        than silently returning a useless payload."""
        a = _autods(monkeypatch)
        with patch.object(
            a, "_http_request",
            return_value={"error": "plan quota exceeded"},
        ):
            with pytest.raises(AdapterError, match="quota"):
                a._autods_request("GET", "/x")

    def test_error_with_data_does_not_raise(self, monkeypatch):
        """If the response includes an id alongside an error,
        treat as informational rather than fatal."""
        a = _autods(monkeypatch)
        with patch.object(
            a, "_http_request",
            return_value={"id": "p1", "error": "stale"},
        ):
            # Should NOT raise
            out = a._autods_request("GET", "/products/p1")
        assert out["id"] == "p1"


# ── search_products ──────────────────────────────────────


_SAMPLE_SEARCH = {
    "results": [
        {
            "id": "autods_p1",
            "title": "Galaxy Projector",
            "description": "Starry night lamp",
            "category": "Lighting",
            "cost": "8.40",
            "price": "24.99",
            "currency": "USD",
            "images": [
                "https://cdn.autods.com/img/a.jpg",
                {"url": "https://cdn.autods.com/img/b.jpg"},
            ],
            "shipping_days_min": 3,
            "shipping_days_max": 5,
            "origin_country": "US",
            "weight_grams": 420,
            "supplier_url": "https://autods.com/p/1",
        },
        {
            "id": "autods_p2",
            "title": "3D Moon Lamp",
            "cost": "5.10",
            "price": "19.99",
        },
    ],
    "total": 2,
    "page": 1,
}


class TestSearchProducts:
    def test_basic_search(self, monkeypatch):
        a = _autods(monkeypatch)
        with patch.object(
            a, "_http_request", return_value=_SAMPLE_SEARCH,
        ) as m:
            result = a.execute(
                Capability.SOURCING_SEARCH_PRODUCTS,
                {"query": "galaxy lamp"},
            )
        assert result.ok
        assert result.adapter == "autods"
        data = result.data
        assert data["query"] == "galaxy lamp"
        assert data["total"] == 2
        first = data["products"][0]
        assert first["sourcing_id"] == "autods_p1"
        assert first["title"] == "Galaxy Projector"
        assert first["cost_usd"] == 8.40
        assert first["suggested_price_usd"] == 24.99
        # Mixed str + dict images flattened to URL list
        assert first["images"] == [
            "https://cdn.autods.com/img/a.jpg",
            "https://cdn.autods.com/img/b.jpg",
        ]
        # Second product has sparse fields — default to 0/empty
        second = data["products"][1]
        assert second["images"] == []
        assert second["shipping_days_min"] == 0

    def test_search_passes_query_params(self, monkeypatch):
        a = _autods(monkeypatch)
        calls: list[tuple] = []

        def capture(method, url, **kw):
            calls.append((method, url, kw.get("params")))
            return _SAMPLE_SEARCH

        with patch.object(a, "_http_request", side_effect=capture):
            a.execute(
                Capability.SOURCING_SEARCH_PRODUCTS,
                {
                    "query": "moon lamp", "limit": 50,
                    "page": 2, "supplier": "aliexpress",
                },
            )
        _method, url, params = calls[0]
        assert "/products/search" in url
        assert params == {
            "q": "moon lamp",
            "limit": 50,
            "page": 2,
            "supplier": "aliexpress",
        }

    def test_search_without_supplier_omits_filter(
        self, monkeypatch,
    ):
        a = _autods(monkeypatch)
        calls: list[tuple] = []

        def capture(method, url, **kw):
            calls.append((method, url, kw.get("params")))
            return _SAMPLE_SEARCH

        with patch.object(a, "_http_request", side_effect=capture):
            a.execute(
                Capability.SOURCING_SEARCH_PRODUCTS,
                {"query": "x"},
            )
        params = calls[0][2]
        assert "supplier" not in params

    def test_search_missing_query_fails_validation(
        self, monkeypatch,
    ):
        """``execute`` catches AdapterValidationError and
        surfaces it as ``result.ok = False`` — owner-facing
        surface matters, not where the exception unwinds."""
        a = _autods(monkeypatch)
        result = a.execute(
            Capability.SOURCING_SEARCH_PRODUCTS, {},
        )
        assert not result.ok
        assert "query" in str(result.error).lower()

    def test_search_empty_results(self, monkeypatch):
        a = _autods(monkeypatch)
        with patch.object(
            a, "_http_request",
            return_value={"results": [], "total": 0},
        ):
            result = a.execute(
                Capability.SOURCING_SEARCH_PRODUCTS,
                {"query": "x"},
            )
        assert result.ok
        assert result.data["products"] == []


# ── get_product ──────────────────────────────────────────


_SAMPLE_PRODUCT = {
    "id": "autods_p42",
    "title": "Anti-Gravity Humidifier",
    "cost": 12.50,
    "price": 34.99,
    "variants": [
        {
            "id": "v1", "sku": "AGH-WHT",
            "cost": 12.50, "stock": 150,
            "attributes": {"color": "white"},
        },
        {
            "id": "v2", "sku": "AGH-BLK",
            "cost": 12.50, "stock": 78,
            "attributes": {"color": "black"},
        },
    ],
    "shipping_days_min": 2,
    "shipping_days_max": 5,
    "origin_country": "US",
    "weight_grams": 600,
}


class TestGetProduct:
    def test_get_product_by_id(self, monkeypatch):
        a = _autods(monkeypatch)
        with patch.object(
            a, "_http_request", return_value=_SAMPLE_PRODUCT,
        ) as m:
            result = a.execute(
                Capability.SOURCING_GET_PRODUCT,
                {"sourcing_id": "autods_p42"},
            )
        assert result.ok
        product = result.data["product"]
        assert product["sourcing_id"] == "autods_p42"
        assert product["cost_usd"] == 12.50
        assert len(product["variants"]) == 2
        assert product["variants"][0]["sku"] == "AGH-WHT"
        # Adapter hit the product-by-id endpoint
        url = m.call_args[0][1]
        assert "/products/autods_p42" in url

    def test_get_product_accepts_product_id_alias(
        self, monkeypatch,
    ):
        a = _autods(monkeypatch)
        with patch.object(
            a, "_http_request", return_value=_SAMPLE_PRODUCT,
        ):
            result = a.execute(
                Capability.SOURCING_GET_PRODUCT,
                {"product_id": "autods_p42"},
            )
        assert result.ok

    def test_missing_id_fails_validation(self, monkeypatch):
        a = _autods(monkeypatch)
        result = a.execute(
            Capability.SOURCING_GET_PRODUCT, {},
        )
        assert not result.ok


# ── create_order ─────────────────────────────────────────


_SAMPLE_ORDER_ACK = {
    "id": "autods_o500",
    "status": "pending",
    "external_order_id": "shopify_1234",
    "items": [
        {
            "sourcing_id": "autods_p42",
            "variant_id": "v1",
            "sku": "AGH-WHT",
            "quantity": 2,
            "cost_usd": 12.50,
        },
    ],
}


class TestCreateOrder:
    def test_create_order_basic(self, monkeypatch):
        a = _autods(monkeypatch)
        captured_body = {}

        def capture(method, url, **kw):
            captured_body["body"] = kw.get("body")
            return _SAMPLE_ORDER_ACK

        with patch.object(a, "_http_request", side_effect=capture):
            result = a.execute(
                Capability.SOURCING_CREATE_ORDER,
                {
                    "items": [{
                        "variant_id": "v1", "quantity": 2,
                    }],
                    "shipping": {
                        "name": "Jane Doe",
                        "address1": "1 Main St",
                        "city": "Boston",
                        "state": "MA",
                        "zip": "02101",
                        "country": "US",
                        "email": "jane@example.com",
                    },
                    "order_ref": "shopify_1234",
                    "note": "Please gift-wrap",
                },
            )
        assert result.ok
        assert result.data["order"]["order_id"] == "autods_o500"
        assert result.data["order"]["status"] == "pending"
        # Request body shape
        body = captured_body["body"]
        assert body["items"] == [
            {"variant_id": "v1", "quantity": 2},
        ]
        assert body["shipping_address"]["country"] == "US"
        assert body["shipping_address"]["zip"] == "02101"
        assert body["external_order_id"] == "shopify_1234"
        assert body["customer_note"] == "Please gift-wrap"

    def test_sku_fallback_when_no_variant_id(self, monkeypatch):
        a = _autods(monkeypatch)
        captured_body = {}

        def capture(method, url, **kw):
            captured_body["body"] = kw.get("body")
            return _SAMPLE_ORDER_ACK

        with patch.object(a, "_http_request", side_effect=capture):
            a.execute(
                Capability.SOURCING_CREATE_ORDER,
                {
                    "items": [{
                        "sku": "AGH-WHT", "quantity": 1,
                    }],
                    "shipping": {
                        "name": "J", "address1": "1",
                        "city": "B", "zip": "02101",
                        "country": "US",
                    },
                },
            )
        assert captured_body["body"]["items"] == [
            {"variant_id": "AGH-WHT", "quantity": 1},
        ]

    def test_invalid_items_fails_validation(self, monkeypatch):
        a = _autods(monkeypatch)
        result = a.execute(
            Capability.SOURCING_CREATE_ORDER,
            {
                "items": [],
                "shipping": {
                    "name": "J", "address1": "1",
                    "city": "B", "zip": "01",
                    "country": "US",
                },
            },
        )
        assert not result.ok

    def test_missing_shipping_fails_validation(self, monkeypatch):
        a = _autods(monkeypatch)
        result = a.execute(
            Capability.SOURCING_CREATE_ORDER,
            {"items": [{"variant_id": "v1", "quantity": 1}]},
        )
        assert not result.ok


# ── get_order_status ─────────────────────────────────────


_SAMPLE_ORDER_STATUS = {
    "id": "autods_o500",
    "status": "shipped",
    "tracking_number": "1Z999AA1012345675",
    "tracking_url": "https://ups.com/track/1Z999AA1012345675",
    "carrier": "UPS",
    "shipped_at": "2026-04-22T10:30:00Z",
    "items": [
        {
            "sourcing_id": "autods_p42",
            "variant_id": "v1",
            "quantity": 2,
            "cost_usd": 12.50,
        },
    ],
}


class TestGetOrderStatus:
    def test_fetches_status(self, monkeypatch):
        a = _autods(monkeypatch)
        with patch.object(
            a, "_http_request",
            return_value=_SAMPLE_ORDER_STATUS,
        ) as m:
            result = a.execute(
                Capability.SOURCING_GET_ORDER_STATUS,
                {"order_id": "autods_o500"},
            )
        assert result.ok
        order = result.data["order"]
        assert order["status"] == "shipped"
        assert order["tracking_number"] == "1Z999AA1012345675"
        assert order["carrier"] == "UPS"
        url = m.call_args[0][1]
        assert "/orders/autods_o500" in url

    def test_missing_order_id_fails_validation(self, monkeypatch):
        a = _autods(monkeypatch)
        result = a.execute(
            Capability.SOURCING_GET_ORDER_STATUS, {},
        )
        assert not result.ok


# ── Bootstrap ────────────────────────────────────────────


class TestBootstrap:
    def test_register_all_includes_autods(self, monkeypatch):
        from core.adapters.sourcing.bootstrap import register_all
        status = register_all()
        assert "autods" in status
        assert "cj_dropshipping" in status

    def test_autods_registered_in_registry(self, monkeypatch):
        from core.adapters.sourcing.bootstrap import register_all
        register_all()
        reg = get_registry()
        names = {a.name for a in reg}
        assert "autods" in names


# ── Router priority ──────────────────────────────────────


class TestRouterPriority:
    def test_cj_wins_when_both_configured(self, monkeypatch):
        """Priority ordering sanity — when both CJ + AutoDS have
        credentials, the router picks CJ first."""
        from core.adapters.sourcing.bootstrap import register_all
        _cfg(
            monkeypatch,
            CJ_DROPSHIPPING_EMAIL="a@b.c",
            CJ_DROPSHIPPING_PASSWORD="pw",
            AUTODS_API_KEY="a" * 40,
        )
        register_all()
        reg = get_registry()
        # Both adapters configured
        adapters = sorted(
            (a for a in reg
             if a.category == AdapterCategory.SOURCING
             and a.is_configured()),
            key=lambda a: -a.priority,
        )
        assert adapters[0].name == "cj_dropshipping"
        assert adapters[1].name == "autods"
