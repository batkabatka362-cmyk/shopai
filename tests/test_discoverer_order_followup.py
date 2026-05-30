"""Tests for order_followup discoverer (Wave 825)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from core.automation.discoverers.order_followup import (
    _classify_order,
    _lookback_days,
    discover_order_followup,
)
from core.automation.payload_discoverer import (
    discover, has_discoverer,
)


class TestRegistryWireup:

    def test_registered_after_import(self):
        assert has_discoverer("order_followup")

    def test_dispatch_via_registry(self):
        with patch(
            "core.automation.discoverers.order_followup."
            "_fetch_orders",
            return_value=[],
        ):
            r = discover("order_followup")
        assert r.ok
        assert r.payload == []


class TestClassifyOrder:

    def _aged(self, days: int) -> str:
        return (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

    def test_refund_signals_needs_attention(self):
        assert _classify_order({
            "id": "x",
            "refunds": [{"id": "r1"}],
        }) == "shopai-followup-needs-attention"

    def test_dispute_signals_needs_attention(self):
        assert _classify_order({
            "id": "x",
            "dispute_id": "d1",
        }) == "shopai-followup-needs-attention"

    def test_delivered_signals_delivery_confirmed(self):
        assert _classify_order({
            "id": "x",
            "fulfillment_status": "fulfilled",
            "fulfillments": [{"status": "delivered"}],
        }) == "shopai-followup-delivery-confirmed"

    def test_unfulfilled_signals_pending(self):
        assert _classify_order({
            "id": "x",
            "fulfillment_status": "partial",
        }) == "shopai-followup-pending-review"

    def test_thank_you_window(self):
        assert _classify_order({
            "id": "x",
            "fulfillment_status": "fulfilled",
            "fulfillments": [{"status": "in_transit"}],
            "created_at": self._aged(5),
        }) == "shopai-followup-thank-you-sent"

    def test_survey_window(self):
        assert _classify_order({
            "id": "x",
            "fulfillment_status": "fulfilled",
            "fulfillments": [{"status": "in_transit"}],
            "created_at": self._aged(14),
        }) == "shopai-followup-survey-sent"

    def test_too_recent_falls_back_to_pending(self):
        assert _classify_order({
            "id": "x",
            "fulfillment_status": "fulfilled",
            "fulfillments": [{"status": "in_transit"}],
            "created_at": self._aged(1),
        }) == "shopai-followup-pending-review"


class TestDiscover:

    def test_empty_payload(self):
        with patch(
            "core.automation.discoverers.order_followup."
            "_fetch_orders",
            return_value=[],
        ):
            r = discover_order_followup()
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
                "refunds": [{"id": "r1"}],
            },
        ]
        with patch(
            "core.automation.discoverers.order_followup."
            "_fetch_orders",
            return_value=orders,
        ):
            r = discover_order_followup()
        assert len(r.payload) == 2
        tags = sorted(p["tag"] for p in r.payload)
        assert tags == [
            "shopai-followup-delivery-confirmed",
            "shopai-followup-needs-attention",
        ]
        for p in r.payload:
            assert p["action"] == "tag_followup"

    def test_fetch_raise_captured(self):
        def explode():
            raise RuntimeError("network down")
        with patch(
            "core.automation.discoverers.order_followup."
            "_fetch_orders",
            side_effect=explode,
        ):
            r = discover_order_followup()
        assert not r.ok
        assert "network down" in r.error


class TestLookbackDays:

    def test_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_ORDER_FOLLOWUP_DISCOVER_DAYS",
            raising=False,
        )
        assert _lookback_days() == 30

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_ORDER_FOLLOWUP_DISCOVER_DAYS", "14",
        )
        assert _lookback_days() == 14
