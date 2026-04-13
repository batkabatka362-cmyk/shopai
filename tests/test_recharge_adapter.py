"""Tests for the ReCharge subscription adapter.

Real HTTP calls are forbidden — every test patches
``_http_request`` to return canned responses.
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
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("RECHARGE_API_TOKEN", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_recharge(monkeypatch, *, key="sk_test_abc123"):
    monkeypatch.setenv("RECHARGE_API_TOKEN", key)
    get_config().reload()


class TestReChargeMetadata:
    def test_metadata(self):
        from core.adapters.subscription.recharge import ReChargeAdapter
        a = ReChargeAdapter()
        assert a.name == "recharge"
        assert a.category == AdapterCategory.SUBSCRIPTION
        assert Capability.SUBSCRIPTION_MANAGE in a.capabilities
        assert a.priority == 90

    def test_unconfigured_without_key(self):
        from core.adapters.subscription.recharge import ReChargeAdapter
        assert not ReChargeAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.subscription.recharge import ReChargeAdapter
        _configure_recharge(monkeypatch)
        assert ReChargeAdapter().is_configured()


class TestReChargeAuth:
    def test_uses_recharge_header(self, monkeypatch):
        from core.adapters.subscription.recharge import ReChargeAdapter
        _configure_recharge(monkeypatch, key="my-token")
        a = ReChargeAdapter()
        headers = a._auth_headers()
        assert headers["X-Recharge-Access-Token"] == "my-token"
        assert "2021-11" in headers["X-Recharge-Version"]


class TestReChargeList:
    def test_list_subscriptions(self, monkeypatch):
        from core.adapters.subscription.recharge import ReChargeAdapter
        _configure_recharge(monkeypatch)
        a = ReChargeAdapter()

        raw = {"subscriptions": [
            {"id": 1, "status": "ACTIVE", "product_title": "Coffee"},
            {"id": 2, "status": "ACTIVE", "product_title": "Tea"},
        ]}

        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.SUBSCRIPTION_MANAGE,
                {"action": "list", "customer_id": "123"},
            )

        assert result.ok
        assert result.data["count"] == 2

    def test_get_subscription_requires_id(self, monkeypatch):
        from core.adapters.subscription.recharge import ReChargeAdapter
        _configure_recharge(monkeypatch)
        a = ReChargeAdapter()

        result = a.execute(
            Capability.SUBSCRIPTION_MANAGE,
            {"action": "get"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


class TestReChargeCreate:
    def test_create_requires_fields(self, monkeypatch):
        from core.adapters.subscription.recharge import ReChargeAdapter
        _configure_recharge(monkeypatch)
        a = ReChargeAdapter()

        result = a.execute(
            Capability.SUBSCRIPTION_MANAGE,
            {"action": "create", "address_id": "456"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_create_happy_path(self, monkeypatch):
        from core.adapters.subscription.recharge import ReChargeAdapter
        _configure_recharge(monkeypatch)
        a = ReChargeAdapter()

        raw = {"subscription": {"id": 99, "status": "ACTIVE"}}

        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.SUBSCRIPTION_MANAGE,
                {
                    "action": "create",
                    "address_id": "456",
                    "next_charge_scheduled_at": "2025-01-15",
                    "shopify_variant_id": "789",
                    "quantity": 1,
                },
            )

        assert result.ok
        assert result.data["subscription_id"] == 99


class TestReChargeCancel:
    def test_cancel_subscription(self, monkeypatch):
        from core.adapters.subscription.recharge import ReChargeAdapter
        _configure_recharge(monkeypatch)
        a = ReChargeAdapter()

        raw = {"subscription": {"id": 99, "status": "CANCELLED"}}

        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.SUBSCRIPTION_MANAGE,
                {
                    "action": "cancel",
                    "subscription_id": "99",
                    "cancellation_reason": "too_expensive",
                },
            )

        assert result.ok
        assert result.data["status"] == "CANCELLED"


class TestReChargeBootstrap:
    def test_register_all(self):
        from core.adapters.subscription.bootstrap import register_all
        status = register_all()
        assert "recharge" in status

    def test_router_finds_recharge(self, monkeypatch):
        from core.adapters.subscription.bootstrap import register_all
        _configure_recharge(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.SUBSCRIPTION_MANAGE)
        assert chosen.name == "recharge"
