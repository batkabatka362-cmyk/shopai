"""Tests for fulfillment discoverer (Wave 832)."""
from __future__ import annotations

from unittest.mock import patch

from core.automation.discoverers.fulfillment import (
    _classify_order,
    _default_location_id,
    _limit,
    _pick_location,
    discover_fulfillment,
)
from core.automation.payload_discoverer import (
    discover, has_discoverer,
)


class TestRegistryWireup:

    def test_registered_after_import(self):
        assert has_discoverer("fulfillment")

    def test_dispatch_via_registry(self):
        with patch(
            "core.automation.discoverers.fulfillment."
            "_fetch_orders",
            return_value=[],
        ):
            r = discover("fulfillment")
        assert r.ok
        assert r.source == "shopify_orders"


class TestPickLocation:

    def test_env_default_wins(self):
        assert _pick_location(
            {"line_items": [{"location_id": "loc_a"}]},
            default_lid="ENV_LOC",
        ) == "ENV_LOC"

    def test_first_line_item_location_used(self):
        assert _pick_location(
            {
                "line_items": [
                    {"sku": "x"},
                    {"location_id": "from_line"},
                ],
            },
            default_lid="",
        ) == "from_line"

    def test_no_signal_returns_empty(self):
        assert _pick_location({}, "") == ""


class TestClassifyOrder:

    def test_open_order_routed(self):
        row = _classify_order({
            "id": "gid://shopify/Order/1",
            "fulfillment_status": None,
            "line_items": [{"location_id": "loc1"}],
        }, default_lid="")
        assert row is not None
        assert row["action"] == "route"
        assert row["location_id"] == "loc1"

    def test_fulfilled_order_skipped(self):
        assert _classify_order({
            "id": "x",
            "fulfillment_status": "fulfilled",
        }, default_lid="loc1") is None

    def test_cancelled_skipped(self):
        assert _classify_order({
            "id": "x",
            "cancelled_at": "2026-01-01T00:00:00Z",
        }, default_lid="loc1") is None

    def test_no_id_skipped(self):
        assert _classify_order({
            "id": "",
            "line_items": [{"location_id": "loc1"}],
        }, default_lid="") is None

    def test_no_location_signal_skipped(self):
        assert _classify_order({
            "id": "x",
            "line_items": [{"sku": "y"}],
        }, default_lid="") is None

    def test_non_dict_skipped(self):
        assert _classify_order("nope", "") is None


class TestDiscover:

    def test_empty(self):
        with patch(
            "core.automation.discoverers.fulfillment."
            "_fetch_orders",
            return_value=[],
        ):
            r = discover_fulfillment()
        assert r.ok
        assert r.payload == []

    def test_orders_become_payload(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_FULFILLMENT_DEFAULT_LOCATION_ID",
            raising=False,
        )
        orders = [
            {
                "id": "1",
                "line_items": [{"location_id": "L1"}],
            },
            {
                "id": "2",
                "fulfillment_status": "fulfilled",
            },
            {
                "id": "3",
                "line_items": [{"sku": "no_loc"}],
            },
        ]
        with patch(
            "core.automation.discoverers.fulfillment."
            "_fetch_orders",
            return_value=orders,
        ):
            r = discover_fulfillment()
        assert len(r.payload) == 1
        assert r.payload[0]["order_id"] == "1"
        assert r.payload[0]["location_id"] == "L1"

    def test_env_default_lid_routes_all(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_FULFILLMENT_DEFAULT_LOCATION_ID",
            "ENV_DEFAULT",
        )
        orders = [
            {"id": "1"},
            {"id": "2"},
        ]
        with patch(
            "core.automation.discoverers.fulfillment."
            "_fetch_orders",
            return_value=orders,
        ):
            r = discover_fulfillment()
        assert len(r.payload) == 2
        for row in r.payload:
            assert row["location_id"] == "ENV_DEFAULT"

    def test_fetch_raise_captured(self):
        def explode():
            raise RuntimeError("net down")
        with patch(
            "core.automation.discoverers.fulfillment."
            "_fetch_orders",
            side_effect=explode,
        ):
            r = discover_fulfillment()
        assert not r.ok
        assert "net down" in r.error


class TestEnvKnobs:

    def test_limit_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_FULFILLMENT_DISCOVER_LIMIT",
            raising=False,
        )
        assert _limit() == 100

    def test_default_lid_empty(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_FULFILLMENT_DEFAULT_LOCATION_ID",
            raising=False,
        )
        assert _default_location_id() == ""

    def test_default_lid_override(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_FULFILLMENT_DEFAULT_LOCATION_ID", "ABC",
        )
        assert _default_location_id() == "ABC"
