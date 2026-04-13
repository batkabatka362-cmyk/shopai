"""Tests for Phase 4 shipping adapters + auto_fulfill migration.

Real carrier API calls are forbidden — every test patches
``_http_post`` to return canned responses.

Coverage:

  * ShippingBaseAdapter — validation rules, rate sort, fastest
    selection
  * EasyPostAdapter — Basic auth, POST body shape, response
    parsing, buy-label two-step (quote → id → buy)
  * ShippoAdapter — ShippoToken header, different response
    schema, buy via /transactions/
  * Bootstrap — register_all adds 2 adapters, router picks
    EasyPost when both configured
  * auto_fulfill.py migration — placeholder when no from_address,
    real rates when router answers, graceful failure handling
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterAuthError,
    AdapterCategory,
    AdapterResult,
    AdapterUnavailable,
    AdapterValidationError,
    BaseAdapter,
    Capability,
    get_config,
    get_registry,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)
from core.adapters.errors import AdapterError


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "EASYPOST_API_KEY", "SHIPPO_API_KEY",
        "BRAVE_SEARCH_API_KEY", "SERPER_API_KEY",
        "GROQ_API_KEY", "GEMINI_API_KEY",
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


_VALID_FROM = {
    "street1": "456 Warehouse Rd",
    "city": "Portland",
    "state": "OR",
    "zip": "97205",
    "country": "US",
}
_VALID_TO = {
    "street1": "123 Main St",
    "city": "Seattle",
    "state": "WA",
    "zip": "98101",
    "country": "US",
}
_VALID_PARCEL = {
    "length": 10.0,
    "width": 8.0,
    "height": 4.0,
    "weight": 16.0,
}


# ── ShippingBaseAdapter ──────────────────────────────────────


class TestShippingBaseAdapter:
    def test_validate_address_rejects_non_dict(self):
        from core.adapters.shipping.easypost import EasyPostAdapter
        a = EasyPostAdapter()
        with pytest.raises(AdapterValidationError):
            a._validate_address("not a dict", label="from_address")

    def test_validate_address_missing_fields(self):
        from core.adapters.shipping.easypost import EasyPostAdapter
        a = EasyPostAdapter()
        with pytest.raises(AdapterValidationError) as exc:
            a._validate_address(
                {"street1": "x"},
                label="to_address",
            )
        msg = str(exc.value)
        assert "city" in msg
        assert "zip" in msg
        assert "country" in msg

    def test_validate_parcel_missing_fields(self):
        from core.adapters.shipping.easypost import EasyPostAdapter
        a = EasyPostAdapter()
        with pytest.raises(AdapterValidationError):
            a._validate_parcel({"length": 10, "width": 8})

    def test_validate_parcel_rejects_zero_dimensions(self):
        from core.adapters.shipping.easypost import EasyPostAdapter
        a = EasyPostAdapter()
        with pytest.raises(AdapterValidationError):
            a._validate_parcel({
                "length": 0, "width": 8, "height": 4, "weight": 16,
            })

    def test_validate_parcel_rejects_non_numeric(self):
        from core.adapters.shipping.easypost import EasyPostAdapter
        a = EasyPostAdapter()
        with pytest.raises(AdapterValidationError):
            a._validate_parcel({
                "length": "abc", "width": 8, "height": 4, "weight": 16,
            })

    def test_fastest_rate_picks_lowest_delivery_days(self):
        from core.adapters.shipping._base import ShippingBaseAdapter
        rates = [
            {"rate": 5.0, "delivery_days": 7},
            {"rate": 10.0, "delivery_days": 2},
            {"rate": 8.0, "delivery_days": 3},
        ]
        fastest = ShippingBaseAdapter._fastest_rate(rates)
        assert fastest is not None
        assert fastest["delivery_days"] == 2

    def test_fastest_rate_tiebreak_by_price(self):
        from core.adapters.shipping._base import ShippingBaseAdapter
        rates = [
            {"rate": 10.0, "delivery_days": 2},
            {"rate": 8.0, "delivery_days": 2},
        ]
        fastest = ShippingBaseAdapter._fastest_rate(rates)
        assert fastest["rate"] == 8.0

    def test_fastest_rate_empty_list(self):
        from core.adapters.shipping._base import ShippingBaseAdapter
        assert ShippingBaseAdapter._fastest_rate([]) is None


# ── EasyPostAdapter ──────────────────────────────────────────


class TestEasyPostAdapter:
    def test_metadata(self):
        from core.adapters.shipping.easypost import EasyPostAdapter
        a = EasyPostAdapter()
        assert a.name == "easypost"
        assert a.category == AdapterCategory.LOGISTICS
        assert Capability.SHIPPING_RATE_QUOTE in a.capabilities
        assert Capability.SHIPPING_LABEL_BUY in a.capabilities
        assert a.priority == 95  # higher than Shippo
        assert a.free_tier_monthly_limit == 10_000

    def test_unconfigured_without_api_key(self):
        from core.adapters.shipping.easypost import EasyPostAdapter
        assert not EasyPostAdapter().is_configured()

    def test_configured_when_env_set(self, monkeypatch):
        from core.adapters.shipping.easypost import EasyPostAdapter
        monkeypatch.setenv("EASYPOST_API_KEY", "EZAK_test")
        get_config().reload()
        assert EasyPostAdapter().is_configured()

    def test_rate_quote_happy_path(self, monkeypatch):
        from core.adapters.shipping.easypost import EasyPostAdapter
        monkeypatch.setenv("EASYPOST_API_KEY", "EZAK_test")
        get_config().reload()

        a = EasyPostAdapter()
        with patch.object(a, "_http_post", return_value={
            "id": "shp_abc123",
            "rates": [
                {
                    "id": "rate_usps_priority",
                    "carrier": "USPS",
                    "service": "Priority",
                    "rate": "8.95",
                    "currency": "USD",
                    "delivery_days": 3,
                    "delivery_date": "2026-04-11",
                },
                {
                    "id": "rate_ups_ground",
                    "carrier": "UPS",
                    "service": "Ground",
                    "rate": "12.50",
                    "currency": "USD",
                    "delivery_days": 4,
                },
            ],
        }) as mocked:
            result = a.execute(
                Capability.SHIPPING_RATE_QUOTE,
                {
                    "from_address": _VALID_FROM,
                    "to_address": _VALID_TO,
                    "parcel": _VALID_PARCEL,
                },
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["shipment_id"] == "shp_abc123"

        # Sort by price — USPS ($8.95) comes before UPS ($12.50)
        assert result.data["rates"][0]["carrier"] == "USPS"
        assert result.data["rates"][0]["rate"] == 8.95
        assert result.data["cheapest"]["carrier"] == "USPS"
        assert result.data["fastest"]["carrier"] == "USPS"  # 3 < 4 days

        # Verify Basic auth header (base64(key:))
        headers = mocked.call_args.kwargs["headers"]
        auth = headers["Authorization"]
        assert auth.startswith("Basic ")

        # Verify the POST body shape
        body = mocked.call_args.args[1]
        assert "shipment" in body
        assert body["shipment"]["to_address"]["zip"] == "98101"
        assert body["shipment"]["from_address"]["zip"] == "97205"
        assert body["shipment"]["parcel"]["length"] == 10.0

    def test_rate_quote_empty_rates(self, monkeypatch):
        from core.adapters.shipping.easypost import EasyPostAdapter
        monkeypatch.setenv("EASYPOST_API_KEY", "k")
        get_config().reload()
        a = EasyPostAdapter()
        with patch.object(a, "_http_post", return_value={"id": "shp_1", "rates": []}):
            result = a.execute(
                Capability.SHIPPING_RATE_QUOTE,
                {"from_address": _VALID_FROM, "to_address": _VALID_TO,
                 "parcel": _VALID_PARCEL},
            )
        assert result.ok
        assert result.data["count"] == 0
        assert result.data["cheapest"] is None
        assert result.data["fastest"] is None

    def test_rate_quote_missing_address_validates(self, monkeypatch):
        from core.adapters.shipping.easypost import EasyPostAdapter
        monkeypatch.setenv("EASYPOST_API_KEY", "k")
        get_config().reload()
        a = EasyPostAdapter()
        result = a.execute(
            Capability.SHIPPING_RATE_QUOTE,
            {"from_address": _VALID_FROM, "parcel": _VALID_PARCEL},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_buy_label_happy_path(self, monkeypatch):
        from core.adapters.shipping.easypost import EasyPostAdapter
        monkeypatch.setenv("EASYPOST_API_KEY", "k")
        get_config().reload()
        a = EasyPostAdapter()
        with patch.object(a, "_http_post", return_value={
            "id": "shp_abc123",
            "tracking_code": "9400111899223197428490",
            "postage_label": {
                "label_url": "https://easypost.com/labels/abc.pdf",
                "label_file_type": "PDF",
            },
            "tracker": {
                "public_url": "https://track.easypost.com/abc",
            },
            "selected_rate": {
                "carrier": "USPS",
                "service": "Priority",
                "rate": "8.95",
                "currency": "USD",
            },
        }):
            result = a.execute(
                Capability.SHIPPING_LABEL_BUY,
                {
                    "rate_id": "rate_usps_priority",
                    "shipment_id": "shp_abc123",
                },
            )
        assert result.ok
        assert result.data["tracking_code"] == "9400111899223197428490"
        assert result.data["label_url"].endswith(".pdf")
        assert result.data["carrier"] == "USPS"
        assert result.data["rate"] == 8.95

    def test_buy_label_requires_shipment_id(self, monkeypatch):
        """EasyPost's buy endpoint requires a shipment_id from a
        prior rate-quote call. Adapter raises a clear error
        rather than hitting a bad URL."""
        from core.adapters.shipping.easypost import EasyPostAdapter
        monkeypatch.setenv("EASYPOST_API_KEY", "k")
        get_config().reload()
        a = EasyPostAdapter()
        result = a.execute(
            Capability.SHIPPING_LABEL_BUY,
            {"rate_id": "rate_x"},  # no shipment_id
        )
        assert not result.ok
        assert isinstance(result.error, AdapterError)
        assert "shipment_id" in result.error.reason

    def test_buy_label_requires_rate_id(self, monkeypatch):
        from core.adapters.shipping.easypost import EasyPostAdapter
        monkeypatch.setenv("EASYPOST_API_KEY", "k")
        get_config().reload()
        a = EasyPostAdapter()
        result = a.execute(Capability.SHIPPING_LABEL_BUY, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── ShippoAdapter ────────────────────────────────────────────


class TestShippoAdapter:
    def test_metadata(self):
        from core.adapters.shipping.shippo import ShippoAdapter
        a = ShippoAdapter()
        assert a.name == "shippo"
        assert a.priority == 85  # below EasyPost (95)
        assert a.free_tier_monthly_limit == 30

    def test_uses_shippo_token_header(self, monkeypatch):
        """Shippo uses ``Authorization: ShippoToken {key}`` —
        NOT Bearer. Verify the header is formatted correctly."""
        from core.adapters.shipping.shippo import ShippoAdapter
        monkeypatch.setenv("SHIPPO_API_KEY", "shippo_test")
        get_config().reload()
        a = ShippoAdapter()
        headers = a._auth_headers()
        assert headers["Authorization"] == "ShippoToken shippo_test"

    def test_rate_quote_parses_shippo_schema(self, monkeypatch):
        """Shippo's rate schema has ``amount`` + ``estimated_days``
        + nested servicelevel — different from EasyPost."""
        from core.adapters.shipping.shippo import ShippoAdapter
        monkeypatch.setenv("SHIPPO_API_KEY", "k")
        get_config().reload()
        a = ShippoAdapter()
        with patch.object(a, "_http_post", return_value={
            "object_id": "shipment_abc",
            "rates": [
                {
                    "object_id": "rate_usps_priority",
                    "provider": "USPS",
                    "servicelevel": {
                        "name": "Priority Mail",
                        "token": "usps_priority",
                    },
                    "amount": "8.50",
                    "currency": "USD",
                    "estimated_days": 3,
                },
                {
                    "object_id": "rate_dhl_express",
                    "provider": "DHL",
                    "servicelevel": {"name": "Express"},
                    "amount": "25.00",
                    "currency": "USD",
                    "estimated_days": 1,
                },
            ],
        }):
            result = a.execute(
                Capability.SHIPPING_RATE_QUOTE,
                {"from_address": _VALID_FROM, "to_address": _VALID_TO,
                 "parcel": _VALID_PARCEL},
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["shipment_id"] == "shipment_abc"
        # Cheapest = USPS (8.50)
        assert result.data["cheapest"]["carrier"] == "USPS"
        assert result.data["cheapest"]["service"] == "Priority Mail"
        # Fastest = DHL (1 day)
        assert result.data["fastest"]["carrier"] == "DHL"

    def test_buy_label_posts_to_transactions(self, monkeypatch):
        from core.adapters.shipping.shippo import ShippoAdapter
        monkeypatch.setenv("SHIPPO_API_KEY", "k")
        get_config().reload()
        a = ShippoAdapter()

        captured_url = {}
        def fake_post(url, body, headers):
            captured_url["url"] = url
            captured_url["body"] = body
            return {
                "object_id": "transaction_1",
                "tracking_number": "9400111899223197428490",
                "tracking_url_provider": "https://tools.usps.com/track?tLabels=xxx",
                "label_url": "https://shippo-delivery.s3.amazonaws.com/abc.pdf",
                "label_file_type": "PDF",
                "rate": "8.50",
            }

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.SHIPPING_LABEL_BUY,
                {"rate_id": "rate_usps_priority"},
            )
        assert result.ok
        assert "/transactions/" in captured_url["url"]
        assert captured_url["body"]["rate"] == "rate_usps_priority"
        assert result.data["tracking_code"] == "9400111899223197428490"


# ── Bootstrap ────────────────────────────────────────────────


class TestShippingBootstrap:
    def test_register_all_adds_two_adapters(self):
        from core.adapters.shipping.bootstrap import register_all
        status = register_all()
        assert set(status.keys()) == {"easypost", "shippo"}

    def test_register_all_idempotent(self):
        from core.adapters.shipping.bootstrap import register_all
        register_all()
        register_all()
        assert len(get_registry()) == 2

    def test_router_picks_easypost_when_configured(self, monkeypatch):
        from core.adapters.shipping.bootstrap import register_all
        monkeypatch.setenv("EASYPOST_API_KEY", "k")
        monkeypatch.setenv("SHIPPO_API_KEY", "k")
        get_config().reload()
        register_all()
        chosen = get_router().route(Capability.SHIPPING_RATE_QUOTE)
        assert chosen.name == "easypost"  # priority 95 > 85

    def test_router_falls_back_to_shippo_when_easypost_missing(self, monkeypatch):
        from core.adapters.shipping.bootstrap import register_all
        monkeypatch.setenv("SHIPPO_API_KEY", "k")
        get_config().reload()
        register_all()
        chosen = get_router().route(Capability.SHIPPING_RATE_QUOTE)
        assert chosen.name == "shippo"


# ── auto_fulfill.py migration ────────────────────────────────


class TestAutoFulfillMigration:
    def _base_order(self, **extra):
        order = {
            "id": "o1",
            "total_price": 50.0,
            "financial_status": "paid",
            "line_items": [],
            "shipping_address": {
                "address1": "123 Main St",
                "city": "Seattle",
                "zip": "98101",
                "country_code": "US",
            },
        }
        order.update(extra)
        return order

    def test_no_from_address_returns_placeholder(self):
        from execution.fulfillment.auto_fulfill import FulfillmentAutomation
        ff = FulfillmentAutomation()
        r = ff.process_orders([self._base_order()], [])
        first = r["results"][0]
        assert first["status"] == "fulfillable"
        assert first["shipping_rate_source"] == "adapter_required"

    def test_no_router_adapter_returns_placeholder(self):
        """from_address + parcel supplied but no carrier adapter
        is registered → placeholder."""
        from execution.fulfillment.auto_fulfill import FulfillmentAutomation
        ff = FulfillmentAutomation()
        r = ff.process_orders(
            [self._base_order()],
            [],
            from_address={
                "street1": "456", "city": "Portland",
                "zip": "97205", "country": "US",
            },
            default_parcel={"length": 10, "width": 8, "height": 4, "weight": 16},
        )
        assert r["results"][0]["shipping_rate_source"] == "adapter_required"

    def test_real_rates_from_adapter(self):
        """When a shipping adapter IS registered, real rates
        appear in the result dict."""
        from execution.fulfillment.auto_fulfill import FulfillmentAutomation

        class _FakeShip(BaseAdapter):
            name = "fake_ship"
            category = AdapterCategory.LOGISTICS
            capabilities = {Capability.SHIPPING_RATE_QUOTE}
            priority = 100
            def is_configured(self): return True
            def _execute(self, c, p):
                return AdapterResult.success(
                    adapter=self.name,
                    capability=c.value,
                    data={
                        "rates": [
                            {"rate_id": "r1", "carrier": "USPS",
                             "service": "Priority", "rate": 8.95,
                             "currency": "USD", "delivery_days": 3,
                             "delivery_date": ""},
                        ],
                        "count": 1,
                        "cheapest": {
                            "rate_id": "r1", "carrier": "USPS",
                            "service": "Priority", "rate": 8.95,
                            "currency": "USD", "delivery_days": 3,
                            "delivery_date": "",
                        },
                        "fastest": None,
                        "shipment_id": "shp_1",
                    },
                )
        get_registry().register(_FakeShip())

        ff = FulfillmentAutomation()
        r = ff.process_orders(
            [self._base_order()],
            [],
            from_address={
                "street1": "456", "city": "Portland",
                "zip": "97205", "country": "US",
            },
            default_parcel={"length": 10, "width": 8, "height": 4, "weight": 16},
        )
        first = r["results"][0]
        assert first["shipping_rate_source"] == "fake_ship"
        assert len(first["shipping_rates"]) == 1
        assert first["cheapest_rate"]["rate"] == 8.95
        assert first["status"] == "fulfillable"

    def test_adapter_failure_marks_rate_error(self):
        """Adapter failure (non-NoAdapterAvailable) marks the
        order with ``adapter_error`` but still keeps the order
        fulfillable — shipping failure shouldn't break
        fulfillment."""
        from execution.fulfillment.auto_fulfill import FulfillmentAutomation

        class _Broken(BaseAdapter):
            name = "broken_ship"
            category = AdapterCategory.LOGISTICS
            capabilities = {Capability.SHIPPING_RATE_QUOTE}
            def is_configured(self): return True
            def _execute(self, c, p):
                raise AdapterUnavailable(self.name, "down")
        get_registry().register(_Broken())

        ff = FulfillmentAutomation()
        r = ff.process_orders(
            [self._base_order()],
            [],
            from_address={
                "street1": "x", "city": "y", "zip": "1", "country": "US",
            },
            default_parcel={"length": 10, "width": 8, "height": 4, "weight": 16},
        )
        first = r["results"][0]
        assert first["status"] == "fulfillable"
        assert first["shipping_rate_source"] == "adapter_error"
        assert first["shipping_rate_error"] == "AdapterUnavailable"

    def test_missing_zip_returns_placeholder(self):
        from execution.fulfillment.auto_fulfill import FulfillmentAutomation
        ff = FulfillmentAutomation()
        r = ff.process_orders(
            [self._base_order(shipping_address={"country_code": "US"})],
            [],
            from_address={
                "street1": "x", "city": "y", "zip": "1", "country": "US",
            },
            default_parcel={"length": 10, "width": 8, "height": 4, "weight": 16},
        )
        assert r["results"][0]["shipping_rate_source"] == "adapter_required"

    def test_order_parcel_overrides_default(self):
        """If the order itself carries parcel dimensions, they
        win over the caller's default_parcel."""
        from execution.fulfillment.auto_fulfill import FulfillmentAutomation

        captured_parcel = {}

        class _CaptureShip(BaseAdapter):
            name = "capture_ship"
            category = AdapterCategory.LOGISTICS
            capabilities = {Capability.SHIPPING_RATE_QUOTE}
            priority = 100
            def is_configured(self): return True
            def _execute(self, c, p):
                captured_parcel.update(p.get("parcel", {}))
                return AdapterResult.success(
                    adapter=self.name, capability=c.value,
                    data={"rates": [], "count": 0,
                          "cheapest": None, "fastest": None,
                          "shipment_id": ""},
                )
        get_registry().register(_CaptureShip())

        order = self._base_order(parcel={
            "length": 99, "width": 88, "height": 77, "weight": 66,
        })
        ff = FulfillmentAutomation()
        ff.process_orders(
            [order],
            [],
            from_address={
                "street1": "x", "city": "y", "zip": "1", "country": "US",
            },
            default_parcel={"length": 10, "width": 8, "height": 4, "weight": 16},
        )
        # Order-level parcel wins
        assert captured_parcel["length"] == 99
        assert captured_parcel["width"] == 88
