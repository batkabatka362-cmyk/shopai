"""Tests for customer_outreach discoverer (Wave 829)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from core.automation.discoverers.customer_outreach import (
    _classify_customer,
    _limit,
    _vip_threshold,
    discover_customer_outreach,
)
from core.automation.payload_discoverer import (
    discover, has_discoverer,
)


def _aged_iso(days: int) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).isoformat()


class TestRegistryWireup:

    def test_registered_after_import(self):
        assert has_discoverer("customer_outreach")

    def test_dispatch_via_registry(self):
        with patch(
            "core.automation.discoverers.customer_outreach."
            "_fetch_customers",
            return_value=[],
        ):
            r = discover("customer_outreach")
        assert r.ok
        assert r.source == "shopify_customers"


class TestClassifyCustomer:

    def test_vip_threshold(self):
        assert _classify_customer({
            "id": "c1",
            "total_spent": 1000.0,
        }, vip_usd=500.0) == "shopai-outreach-vip-engagement"

    def test_winback_after_90_days(self):
        assert _classify_customer({
            "id": "c1",
            "orders_count": 3,
            "last_order_at": _aged_iso(100),
            "total_spent": 50.0,
        }, vip_usd=500.0) == "shopai-outreach-winback"

    def test_at_risk_30_to_90_days(self):
        assert _classify_customer({
            "id": "c1",
            "orders_count": 2,
            "last_order_at": _aged_iso(45),
            "total_spent": 50.0,
        }, vip_usd=500.0) == "shopai-outreach-at-risk"

    def test_reviewed_recent_buyer(self):
        assert _classify_customer({
            "id": "c1",
            "orders_count": 5,
            "last_order_at": _aged_iso(5),
            "total_spent": 50.0,
        }, vip_usd=500.0) == "shopai-outreach-reviewed"

    def test_followup_no_orders_aged_account(self):
        assert _classify_customer({
            "id": "c1",
            "orders_count": 0,
            "created_at": _aged_iso(14),
        }, vip_usd=500.0) == "shopai-outreach-followup-needed"

    def test_brand_new_customer_unclassified(self):
        # 0 orders + < 7 days since signup -> None (skip)
        assert _classify_customer({
            "id": "c1",
            "orders_count": 0,
            "created_at": _aged_iso(2),
        }, vip_usd=500.0) is None

    def test_non_dict_returns_none(self):
        assert _classify_customer("not a dict", 500.0) is None

    def test_bad_spent_falls_back_to_zero(self):
        # garbage total_spent doesn't crash; still classifies
        # via other signals
        assert _classify_customer({
            "id": "c1",
            "total_spent": "not-a-number",
            "orders_count": 1,
            "last_order_at": _aged_iso(45),
        }, vip_usd=500.0) == "shopai-outreach-at-risk"


class TestDiscover:

    def test_empty_payload(self):
        with patch(
            "core.automation.discoverers.customer_outreach."
            "_fetch_customers",
            return_value=[],
        ):
            r = discover_customer_outreach()
        assert r.ok
        assert r.payload == []

    def test_customers_become_payload(self):
        customers = [
            {
                "id": "c1",
                "total_spent": 800.0,
            },
            {
                "id": "c2",
                "orders_count": 0,
                "created_at": _aged_iso(15),
            },
            {  # unclassifiable
                "id": "c3",
                "orders_count": 0,
                "created_at": _aged_iso(2),
            },
        ]
        with patch(
            "core.automation.discoverers.customer_outreach."
            "_fetch_customers",
            return_value=customers,
        ):
            r = discover_customer_outreach()
        assert len(r.payload) == 2
        tags = sorted(p["tag"] for p in r.payload)
        assert tags == [
            "shopai-outreach-followup-needed",
            "shopai-outreach-vip-engagement",
        ]
        for p in r.payload:
            assert p["action"] == "tag_outreach"

    def test_fetch_raise_captured(self):
        def explode(*args, **kwargs):
            raise RuntimeError("api down")
        with patch(
            "core.automation.discoverers.customer_outreach."
            "_fetch_customers",
            side_effect=explode,
        ):
            r = discover_customer_outreach()
        assert not r.ok
        assert "api down" in r.error


class TestEnvKnobs:

    def test_limit_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_CUSTOMER_OUTREACH_DISCOVER_LIMIT",
            raising=False,
        )
        assert _limit() == 200

    def test_limit_override(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_CUSTOMER_OUTREACH_DISCOVER_LIMIT", "50",
        )
        assert _limit() == 50

    def test_vip_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_CUSTOMER_OUTREACH_VIP_USD",
            raising=False,
        )
        assert _vip_threshold() == 500.0

    def test_vip_override(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_CUSTOMER_OUTREACH_VIP_USD", "1000",
        )
        assert _vip_threshold() == 1000.0
