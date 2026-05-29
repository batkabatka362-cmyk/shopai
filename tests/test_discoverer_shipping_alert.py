"""Tests for shipping_alert discoverer (Wave 821)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from core.automation.discoverers.shipping_alert import (
    _classify_order,
    _lookback_days,
    discover_shipping_alert,
)
from core.automation.payload_discoverer import (
    DiscoveryResult, discover, has_discoverer,
)


class TestRegistryWireup:

    def test_registered_after_import(self):
        # Importing core/automation/discoverers/shipping_alert
        # is enough to trigger registration.
        assert has_discoverer("shipping_alert")

    def test_discover_via_registry(self):
        # Calling the canonical entry-point should hit the
        # registered fn. We mock the Shopify fetch so the test
        # is deterministic.
        with patch(
            "core.automation.discoverers.shipping_alert."
            "_fetch_recent_orders",
            return_value=[],
        ):
            r = discover("shipping_alert")
        assert isinstance(r, DiscoveryResult)
        assert r.ok
        assert r.payload == []
        assert r.source == "shopify_orders"


class TestClassifyOrder:

    def _aged(self, days: int) -> str:
        return (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

    def test_cancelled_order(self):
        assert _classify_order({
            "id": "x",
            "cancelled_at": "2026-01-01T00:00:00Z",
        }) == "shopai-shipping-refused"

    def test_delivered_order(self):
        assert _classify_order({
            "id": "x",
            "fulfillment_status": "fulfilled",
            "fulfillments": [
                {"status": "delivered"},
            ],
        }) == "shopai-shipping-delivered"

    def test_delivered_via_delivered_at(self):
        assert _classify_order({
            "id": "x",
            "fulfillment_status": "fulfilled",
            "fulfillments": [
                {"delivered_at": "2026-01-01T00:00:00Z"},
            ],
        }) == "shopai-shipping-delivered"

    def test_in_transit_recent(self):
        assert _classify_order({
            "id": "x",
            "fulfillment_status": "fulfilled",
            "fulfillments": [{"status": "in_transit"}],
            "created_at": self._aged(3),
        }) == "shopai-shipping-in-transit"

    def test_delayed_after_14_days(self):
        assert _classify_order({
            "id": "x",
            "fulfillment_status": "fulfilled",
            "fulfillments": [{"status": "in_transit"}],
            "created_at": self._aged(15),
        }) == "shopai-shipping-delayed"

    def test_lost_after_30_days(self):
        assert _classify_order({
            "id": "x",
            "fulfillment_status": "fulfilled",
            "fulfillments": [{"status": "in_transit"}],
            "created_at": self._aged(45),
        }) == "shopai-shipping-lost"

    def test_unfulfilled_returns_none(self):
        assert _classify_order({
            "id": "x",
            "fulfillment_status": "partial",
        }) is None

    def test_missing_fulfillment_status_returns_none(self):
        assert _classify_order({"id": "x"}) is None

    def test_no_created_at_falls_back_to_in_transit(self):
        assert _classify_order({
            "id": "x",
            "fulfillment_status": "fulfilled",
            "fulfillments": [],
        }) == "shopai-shipping-in-transit"

    def test_bad_created_at_falls_back(self):
        assert _classify_order({
            "id": "x",
            "fulfillment_status": "fulfilled",
            "fulfillments": [],
            "created_at": "not a date",
        }) == "shopai-shipping-in-transit"


class TestDiscoverShippingAlert:

    def test_no_orders_empty_payload(self):
        with patch(
            "core.automation.discoverers.shipping_alert."
            "_fetch_recent_orders",
            return_value=[],
        ):
            r = discover_shipping_alert()
        assert r.ok
        assert r.payload == []

    def test_orders_become_payload(self):
        orders = [
            {
                "id": "gid://shopify/Order/1",
                "fulfillment_status": "fulfilled",
                "fulfillments": [{"status": "delivered"}],
            },
            {
                "id": "gid://shopify/Order/2",
                "cancelled_at": "2026-01-01T00:00:00Z",
            },
            # Unclassifiable -- no signal
            {"id": "gid://shopify/Order/3"},
        ]
        with patch(
            "core.automation.discoverers.shipping_alert."
            "_fetch_recent_orders",
            return_value=orders,
        ):
            r = discover_shipping_alert()
        assert r.ok
        # Only 2 of 3 orders classifiable
        assert len(r.payload) == 2
        tags = sorted(p["tag"] for p in r.payload)
        assert tags == [
            "shopai-shipping-delivered",
            "shopai-shipping-refused",
        ]
        for p in r.payload:
            assert p["action"] == "tag_shipping"
            assert p["signal_source"] == (
                "shipping_alert_discoverer"
            )

    def test_fetch_raise_captured(self):
        def explode():
            raise RuntimeError("network down")
        with patch(
            "core.automation.discoverers.shipping_alert."
            "_fetch_recent_orders",
            side_effect=explode,
        ):
            r = discover_shipping_alert()
        assert not r.ok
        assert "network down" in r.error

    def test_skips_orders_with_no_id(self):
        orders = [
            {
                "id": "",
                "fulfillment_status": "fulfilled",
                "fulfillments": [{"status": "delivered"}],
            },
        ]
        with patch(
            "core.automation.discoverers.shipping_alert."
            "_fetch_recent_orders",
            return_value=orders,
        ):
            r = discover_shipping_alert()
        assert r.payload == []


class TestLookbackDays:

    def test_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS",
            raising=False,
        )
        assert _lookback_days() == 60

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS", "7",
        )
        assert _lookback_days() == 7

    def test_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS", "abc",
        )
        assert _lookback_days() == 60

    def test_clamps_minimum(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS", "0",
        )
        assert _lookback_days() == 1
