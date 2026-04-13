"""Tests for the Zapier automation adapter.

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
    monkeypatch.delenv("ZAPIER_NLA_API_KEY", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_zapier(monkeypatch, *, key="nla-test-key"):
    monkeypatch.setenv("ZAPIER_NLA_API_KEY", key)
    get_config().reload()


class TestZapierMetadata:
    def test_metadata(self):
        from core.adapters.automation.zapier import ZapierAdapter
        a = ZapierAdapter()
        assert a.name == "zapier"
        assert a.category == AdapterCategory.AUTOMATION
        assert Capability.AUTOMATION_TRIGGER in a.capabilities
        assert Capability.AUTOMATION_LIST_ZAPS in a.capabilities
        assert a.priority == 85

    def test_unconfigured_without_key(self):
        from core.adapters.automation.zapier import ZapierAdapter
        assert not ZapierAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.automation.zapier import ZapierAdapter
        _configure_zapier(monkeypatch)
        assert ZapierAdapter().is_configured()


class TestZapierTrigger:
    def test_trigger_requires_action_id(self, monkeypatch):
        from core.adapters.automation.zapier import ZapierAdapter
        _configure_zapier(monkeypatch)
        a = ZapierAdapter()

        result = a.execute(
            Capability.AUTOMATION_TRIGGER,
            {"instructions": "Send a Slack message"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_trigger_requires_instructions(self, monkeypatch):
        from core.adapters.automation.zapier import ZapierAdapter
        _configure_zapier(monkeypatch)
        a = ZapierAdapter()

        result = a.execute(
            Capability.AUTOMATION_TRIGGER,
            {"action_id": "abc123"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_trigger_happy_path(self, monkeypatch):
        from core.adapters.automation.zapier import ZapierAdapter
        _configure_zapier(monkeypatch)
        a = ZapierAdapter()

        raw = {
            "status": "success",
            "result": "Message sent to #general",
        }

        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.AUTOMATION_TRIGGER,
                {
                    "action_id": "slack_send_message",
                    "instructions": "Send 'New order received' to #orders channel",
                },
            )

        assert result.ok
        assert result.data["status"] == "success"
        assert result.data["action_id"] == "slack_send_message"


class TestZapierListZaps:
    def test_list_zaps(self, monkeypatch):
        from core.adapters.automation.zapier import ZapierAdapter
        _configure_zapier(monkeypatch)
        a = ZapierAdapter()

        raw = {
            "results": [
                {"id": "abc", "description": "Send Slack message", "params": {}},
                {"id": "def", "description": "Create Google Sheet row", "params": {}},
            ],
        }

        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.AUTOMATION_LIST_ZAPS,
                {},
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["actions"][0]["description"] == "Send Slack message"


class TestZapierBootstrap:
    def test_register_all(self):
        from core.adapters.automation.bootstrap import register_all
        status = register_all()
        assert "zapier" in status

    def test_router_finds_zapier(self, monkeypatch):
        from core.adapters.automation.bootstrap import register_all
        _configure_zapier(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.AUTOMATION_TRIGGER)
        assert chosen.name == "zapier"
