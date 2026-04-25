"""Wave-5 sourcing extensions — cancel / list / shipping / stock.

Mock-HTTP tests for the four new capabilities added to the
sourcing surface. Both CJ and AutoDS adapters participate;
shipping-methods is CJ-only because AutoDS doesn't expose a
freight-rate endpoint.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterValidationError,
    Capability,
    get_config,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "CJ_DROPSHIPPING_EMAIL", "CJ_DROPSHIPPING_PASSWORD",
        "AUTODS_API_KEY",
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


def _configure_cj(monkeypatch):
    monkeypatch.setenv("CJ_DROPSHIPPING_EMAIL", "ops@deguar.com")
    monkeypatch.setenv("CJ_DROPSHIPPING_PASSWORD", "s" * 12)
    get_config().reload()


def _configure_autods(monkeypatch):
    monkeypatch.setenv("AUTODS_API_KEY", "k" * 40)
    get_config().reload()


# ── Capability enum ─────────────────────────────────────────


class TestNewCapabilities:
    def test_capabilities_defined(self):
        assert (
            Capability("sourcing_cancel_order")
            is Capability.SOURCING_CANCEL_ORDER
        )
        assert (
            Capability("sourcing_list_orders")
            is Capability.SOURCING_LIST_ORDERS
        )
        assert (
            Capability("sourcing_get_shipping_methods")
            is Capability.SOURCING_GET_SHIPPING_METHODS
        )
        assert (
            Capability("sourcing_get_variant_stock")
            is Capability.SOURCING_GET_VARIANT_STOCK
        )


# ── CJ — cancel ─────────────────────────────────────────────


class TestCJCancel:
    def test_requires_order_id(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import (
            CJDropshippingAdapter,
        )
        _configure_cj(monkeypatch)
        a = CJDropshippingAdapter()
        with patch.object(a, "_get_token", return_value="tok"):
            res = a.execute(Capability.SOURCING_CANCEL_ORDER, {})
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_happy_path(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import (
            CJDropshippingAdapter,
        )
        _configure_cj(monkeypatch)
        a = CJDropshippingAdapter()
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured["method"] = method
            captured["path"] = path
            captured["body"] = body
            return {
                "result": True,
                "code": 200,
                "message": "cancelled",
                "_raw": {"ok": True},
            }

        with patch.object(
            a, "_cj_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.SOURCING_CANCEL_ORDER,
                {"order_id": "CJ-1"},
            )
        assert res.ok
        assert (
            captured["path"] == "/shopping/order/cancelOrder"
        )
        assert captured["body"] == {"orderId": "CJ-1"}
        assert res.data["order"]["order_id"] == "CJ-1"
        assert res.data["order"]["status"] == "cancelled"


# ── CJ — list orders ────────────────────────────────────────


class TestCJListOrders:
    def test_list_orders_default_page(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import (
            CJDropshippingAdapter,
        )
        _configure_cj(monkeypatch)
        a = CJDropshippingAdapter()
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured.update({
                "method": method, "path": path, "params": params,
            })
            return {
                "list": [
                    {
                        "orderId": "CJ-1",
                        "orderStatus": "shipped",
                        "trackingNumber": "TRK-1",
                        "orderAmount": "19.99",
                    },
                    "malformed",
                    {
                        "orderId": "CJ-2",
                        "orderStatus": "pending",
                    },
                ],
                "_raw": {},
            }

        with patch.object(
            a, "_cj_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.SOURCING_LIST_ORDERS, {},
            )

        assert res.ok
        assert res.data["total"] == 2
        assert res.data["page"] == 1
        assert res.data["page_size"] == 50
        assert captured["path"] == "/shopping/order/list"
        assert captured["params"]["pageNum"] == 1
        orders = res.data["orders"]
        assert orders[0]["order_id"] == "CJ-1"
        assert orders[0]["status"] == "shipped"
        assert orders[0]["tracking_number"] == "TRK-1"

    def test_list_orders_page_clamped(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import (
            CJDropshippingAdapter,
        )
        _configure_cj(monkeypatch)
        a = CJDropshippingAdapter()
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured["params"] = params
            return {"list": [], "_raw": {}}

        with patch.object(
            a, "_cj_request", side_effect=fake_request,
        ):
            a.execute(
                Capability.SOURCING_LIST_ORDERS,
                {"page_size": 9999, "status": "shipped"},
            )
        assert captured["params"]["pageSize"] == 200
        assert captured["params"]["status"] == "shipped"


# ── CJ — shipping methods ───────────────────────────────────


class TestCJShippingMethods:
    def test_requires_country_and_variant(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import (
            CJDropshippingAdapter,
        )
        _configure_cj(monkeypatch)
        a = CJDropshippingAdapter()
        with patch.object(a, "_get_token", return_value="tok"):
            res = a.execute(
                Capability.SOURCING_GET_SHIPPING_METHODS, {},
            )
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_happy_path_sorted_by_speed(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import (
            CJDropshippingAdapter,
        )
        _configure_cj(monkeypatch)
        a = CJDropshippingAdapter()
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured.update({"path": path, "body": body})
            return {
                "list": [
                    {
                        "logisticName": "Slow Post",
                        "logisticPrice": "3.00",
                        "logisticAging": 20,
                        "logisticAgingMax": 30,
                    },
                    "oops",
                    {
                        "logisticName": "DHL Express",
                        "logisticPrice": "18.50",
                        "logisticAging": 3,
                        "logisticAgingMax": 5,
                    },
                    {
                        "logisticName": "Standard Air",
                        "logisticPrice": "6.00",
                        "logisticAging": 7,
                        "logisticAgingMax": 14,
                    },
                ],
                "_raw": {},
            }

        with patch.object(
            a, "_cj_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.SOURCING_GET_SHIPPING_METHODS,
                {
                    "variant_id": "V-1",
                    "country": "us",
                    "quantity": 3,
                },
            )
        assert res.ok
        assert captured["body"] == {
            "vid": "V-1",
            "countryCode": "US",
            "quantity": 3,
        }
        methods = res.data["methods"]
        # Sorted fastest-first by days_max, then cost.
        assert methods[0]["method_name"] == "DHL Express"
        assert methods[-1]["method_name"] == "Slow Post"
        # Fastest / cheapest helpers pointing correctly.
        assert res.data["fastest"]["method_name"] == "DHL Express"
        assert res.data["cheapest"]["method_name"] == "Slow Post"

    def test_empty_methods_list(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import (
            CJDropshippingAdapter,
        )
        _configure_cj(monkeypatch)
        a = CJDropshippingAdapter()

        def fake_request(method, path, *, body=None, params=None):
            return {"list": [], "_raw": {}}

        with patch.object(
            a, "_cj_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.SOURCING_GET_SHIPPING_METHODS,
                {"variant_id": "V", "country": "US"},
            )
        assert res.ok
        assert res.data["methods"] == []
        assert res.data["fastest"] is None
        assert res.data["cheapest"] is None


# ── CJ — variant stock ──────────────────────────────────────


class TestCJStock:
    def test_requires_variant_id(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import (
            CJDropshippingAdapter,
        )
        _configure_cj(monkeypatch)
        a = CJDropshippingAdapter()
        with patch.object(a, "_get_token", return_value="tok"):
            res = a.execute(
                Capability.SOURCING_GET_VARIANT_STOCK, {},
            )
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_happy_path_sums_warehouses(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import (
            CJDropshippingAdapter,
        )
        _configure_cj(monkeypatch)
        a = CJDropshippingAdapter()

        def fake_request(method, path, *, body=None, params=None):
            return {
                "list": [
                    {"areaEn": "CN", "stock": 120},
                    {"areaEn": "US", "stock": 45},
                    "malformed",
                    {"areaEn": "EU", "stock": -10},  # clamped
                ],
                "_raw": {},
            }

        with patch.object(
            a, "_cj_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.SOURCING_GET_VARIANT_STOCK,
                {"variant_id": "V-9"},
            )
        assert res.ok
        assert res.data["stock"] == 165
        assert res.data["in_stock"] is True
        assert len(res.data["warehouses"]) == 3
        assert res.data["warehouses"][0]["warehouse"] == "CN"

    def test_zero_stock_sets_flag(self, monkeypatch):
        from core.adapters.sourcing.cj_dropshipping import (
            CJDropshippingAdapter,
        )
        _configure_cj(monkeypatch)
        a = CJDropshippingAdapter()

        def fake_request(method, path, *, body=None, params=None):
            return {"list": [{"stock": 0}], "_raw": {}}

        with patch.object(
            a, "_cj_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.SOURCING_GET_VARIANT_STOCK,
                {"variant_id": "V"},
            )
        assert res.ok
        assert res.data["stock"] == 0
        assert res.data["in_stock"] is False


# ── AutoDS — cancel ─────────────────────────────────────────


class TestAutoDSCancel:
    def test_happy_path(self, monkeypatch):
        from core.adapters.sourcing.autods import AutoDSAdapter
        _configure_autods(monkeypatch)
        a = AutoDSAdapter()
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured.update({
                "method": method, "path": path, "body": body,
            })
            return {"ok": True}

        with patch.object(
            a, "_autods_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.SOURCING_CANCEL_ORDER,
                {"order_id": "AD-1"},
            )
        assert res.ok
        assert captured["path"] == "/orders/AD-1/cancel"
        assert captured["body"] == {}
        assert res.data["order"]["status"] == "cancelled"


# ── AutoDS — list orders ────────────────────────────────────


class TestAutoDSListOrders:
    def test_list_orders(self, monkeypatch):
        from core.adapters.sourcing.autods import AutoDSAdapter
        _configure_autods(monkeypatch)
        a = AutoDSAdapter()
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured["params"] = params
            return {
                "results": [
                    {"id": "AD-1", "status": "shipped"},
                    "oops",
                ],
            }

        with patch.object(
            a, "_autods_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.SOURCING_LIST_ORDERS,
                {"page": 2, "page_size": 25},
            )
        assert res.ok
        assert captured["params"]["page"] == 2
        assert captured["params"]["limit"] == 25
        assert res.data["total"] == 1
        assert res.data["orders"][0]["order_id"] == "AD-1"


# ── AutoDS — stock ──────────────────────────────────────────


class TestAutoDSStock:
    def test_stock_by_composite_id(self, monkeypatch):
        from core.adapters.sourcing.autods import AutoDSAdapter
        _configure_autods(monkeypatch)
        a = AutoDSAdapter()
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured["path"] = path
            return {
                "id": "P-1",
                "variants": [
                    {"id": "V-1", "stock": 7},
                    {"id": "V-2", "stock": 3},
                ],
            }

        with patch.object(
            a, "_autods_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.SOURCING_GET_VARIANT_STOCK,
                {"variant_id": "P-1:V-1"},
            )
        assert res.ok
        assert captured["path"] == "/products/P-1"
        assert res.data["stock"] == 7
        assert res.data["in_stock"] is True

    def test_stock_by_product_id_sums_variants(self, monkeypatch):
        from core.adapters.sourcing.autods import AutoDSAdapter
        _configure_autods(monkeypatch)
        a = AutoDSAdapter()

        def fake_request(method, path, *, body=None, params=None):
            return {
                "id": "P-1",
                "variants": [
                    {"id": "V-1", "stock": 7},
                    {"id": "V-2", "stock": 3},
                ],
            }

        with patch.object(
            a, "_autods_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.SOURCING_GET_VARIANT_STOCK,
                {"variant_id": "P-1"},
            )
        assert res.ok
        # Sum of all variant stocks when no ":" in id.
        assert res.data["stock"] == 10

    def test_stock_variant_not_found_returns_zero(
        self, monkeypatch,
    ):
        from core.adapters.sourcing.autods import AutoDSAdapter
        _configure_autods(monkeypatch)
        a = AutoDSAdapter()

        def fake_request(method, path, *, body=None, params=None):
            return {
                "id": "P-1",
                "variants": [{"id": "V-1", "stock": 7}],
            }

        with patch.object(
            a, "_autods_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.SOURCING_GET_VARIANT_STOCK,
                {"variant_id": "P-1:V-NOT-FOUND"},
            )
        assert res.ok
        assert res.data["stock"] == 0
        assert res.data["in_stock"] is False

    def test_autods_does_not_expose_shipping_methods(
        self, monkeypatch,
    ):
        """AutoDS opts out — capability isn't in its set, so
        SmartRouter skips it."""
        from core.adapters.sourcing.autods import AutoDSAdapter
        a = AutoDSAdapter()
        assert (
            Capability.SOURCING_GET_SHIPPING_METHODS
            not in a.capabilities
        )
