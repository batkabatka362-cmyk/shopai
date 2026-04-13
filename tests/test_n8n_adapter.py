"""Tests for the n8n automation adapter."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    Capability,
    get_config,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in ("N8N_BASE_URL", "N8N_API_KEY"):
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


def _configure_full(monkeypatch):
    monkeypatch.setenv("N8N_BASE_URL", "https://n8n.example.com/")
    monkeypatch.setenv("N8N_API_KEY", "n8n-key-123")
    get_config().reload()


def _configure_url_only(monkeypatch):
    monkeypatch.setenv("N8N_BASE_URL", "https://n8n.example.com")
    get_config().reload()


class TestN8NMetadata:
    def test_metadata(self):
        from core.adapters.automation.n8n import N8NAdapter
        a = N8NAdapter()
        assert a.name == "n8n"
        assert a.category == AdapterCategory.AUTOMATION
        assert Capability.AUTOMATION_TRIGGER in a.capabilities
        assert Capability.AUTOMATION_LIST_ZAPS in a.capabilities
        assert a.priority == 80

    def test_unconfigured_without_url(self):
        from core.adapters.automation.n8n import N8NAdapter
        assert not N8NAdapter().is_configured()

    def test_configured_with_url_only(self, monkeypatch):
        from core.adapters.automation.n8n import N8NAdapter
        _configure_url_only(monkeypatch)
        # Webhook mode works without API key.
        assert N8NAdapter().is_configured()

    def test_base_url_strips_trailing_slash(self, monkeypatch):
        from core.adapters.automation.n8n import N8NAdapter
        _configure_full(monkeypatch)
        assert N8NAdapter().base_url == "https://n8n.example.com"


class TestN8NAuthHeaders:
    def test_api_key_header_present_when_set(self, monkeypatch):
        from core.adapters.automation.n8n import N8NAdapter
        _configure_full(monkeypatch)
        headers = N8NAdapter()._auth_headers()
        assert headers["X-N8N-API-KEY"] == "n8n-key-123"

    def test_api_key_header_absent_when_missing(self, monkeypatch):
        from core.adapters.automation.n8n import N8NAdapter
        _configure_url_only(monkeypatch)
        headers = N8NAdapter()._auth_headers()
        assert "X-N8N-API-KEY" not in headers


class TestN8NTrigger:
    def test_trigger_via_webhook_url(self, monkeypatch):
        from core.adapters.automation.n8n import N8NAdapter
        _configure_url_only(monkeypatch)
        a = N8NAdapter()

        raw = {"ok": True}
        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(
                Capability.AUTOMATION_TRIGGER,
                {
                    "webhook_url": "https://hooks.example/abc",
                    "data": {"order_id": 42},
                },
            )

        assert result.ok
        assert result.data["mode"] == "webhook"
        assert result.data["triggered"] is True
        method, url = mocked.call_args[0][:2]
        assert method == "POST"
        assert url == "https://hooks.example/abc"

    def test_trigger_via_webhook_path(self, monkeypatch):
        from core.adapters.automation.n8n import N8NAdapter
        _configure_url_only(monkeypatch)
        a = N8NAdapter()

        raw = {"ok": True}
        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(
                Capability.AUTOMATION_TRIGGER,
                {"webhook_path": "/order-placed", "data": {"order_id": 99}},
            )

        assert result.ok
        url = mocked.call_args[0][1]
        assert url == "https://n8n.example.com/webhook/order-placed"

    def test_trigger_via_workflow_id_requires_api_key(self, monkeypatch):
        from core.adapters.automation.n8n import N8NAdapter
        _configure_url_only(monkeypatch)  # no API key
        a = N8NAdapter()
        result = a.execute(
            Capability.AUTOMATION_TRIGGER,
            {"workflow_id": "wf-1"},
        )
        assert not result.ok

    def test_trigger_via_workflow_id_happy_path(self, monkeypatch):
        from core.adapters.automation.n8n import N8NAdapter
        _configure_full(monkeypatch)
        a = N8NAdapter()

        raw = {"data": {"executionId": "exec-42"}}
        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(
                Capability.AUTOMATION_TRIGGER,
                {"workflow_id": "wf-1", "data": {"foo": "bar"}},
            )

        assert result.ok
        assert result.data["mode"] == "api"
        assert result.data["workflow_id"] == "wf-1"
        assert result.data["execution_id"] == "exec-42"

        url = mocked.call_args[0][1]
        assert url == "https://n8n.example.com/api/v1/workflows/wf-1/execute"

    def test_trigger_missing_identifier(self, monkeypatch):
        from core.adapters.automation.n8n import N8NAdapter
        _configure_url_only(monkeypatch)
        result = N8NAdapter().execute(Capability.AUTOMATION_TRIGGER, {})
        assert not result.ok


class TestN8NListZaps:
    def test_list_happy_path(self, monkeypatch):
        from core.adapters.automation.n8n import N8NAdapter
        _configure_full(monkeypatch)
        a = N8NAdapter()

        raw = {
            "data": [{
                "id": 1,
                "name": "Order Notifications",
                "active": True,
                "tags": [{"name": "orders"}, {"name": "slack"}],
                "updatedAt": "2026-04-01T00:00:00Z",
            }],
        }

        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(
                Capability.AUTOMATION_LIST_ZAPS,
                {"active_only": True},
            )

        assert result.ok
        assert result.data["count"] == 1
        assert result.data["actions"][0]["name"] == "Order Notifications"
        assert "orders" in result.data["actions"][0]["tags"]

        url = mocked.call_args[0][1]
        assert "active=true" in url

    def test_list_requires_api_key(self, monkeypatch):
        from core.adapters.automation.n8n import N8NAdapter
        _configure_url_only(monkeypatch)
        result = N8NAdapter().execute(Capability.AUTOMATION_LIST_ZAPS, {})
        assert not result.ok


class TestN8NBootstrap:
    def test_register_all_includes_n8n(self):
        from core.adapters.automation.bootstrap import register_all
        status = register_all()
        assert "n8n" in status
