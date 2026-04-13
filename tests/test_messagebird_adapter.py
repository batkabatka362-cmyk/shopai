"""Tests for the MessageBird SMS adapter.

Real HTTP calls are forbidden — every test patches
``_http_post`` to return canned responses.
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
    monkeypatch.delenv("MESSAGEBIRD_API_KEY", raising=False)
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_messagebird(monkeypatch, *, key="mb-test-key"):
    monkeypatch.setenv("MESSAGEBIRD_API_KEY", key)
    get_config().reload()


class TestMessageBirdMetadata:
    def test_metadata(self):
        from core.adapters.sms.messagebird import MessageBirdAdapter
        a = MessageBirdAdapter()
        assert a.name == "messagebird"
        assert a.category == AdapterCategory.SMS
        assert Capability.SEND_SMS in a.capabilities
        assert a.priority == 60

    def test_unconfigured_without_key(self):
        from core.adapters.sms.messagebird import MessageBirdAdapter
        assert not MessageBirdAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.sms.messagebird import MessageBirdAdapter
        _configure_messagebird(monkeypatch)
        assert MessageBirdAdapter().is_configured()


class TestMessageBirdAuth:
    def test_auth_header(self, monkeypatch):
        from core.adapters.sms.messagebird import MessageBirdAdapter
        _configure_messagebird(monkeypatch, key="live_key_123")
        a = MessageBirdAdapter()
        headers = a._auth_headers()
        assert headers["Authorization"] == "AccessKey live_key_123"


class TestMessageBirdPayload:
    def test_basic_payload(self, monkeypatch):
        from core.adapters.sms.messagebird import MessageBirdAdapter
        _configure_messagebird(monkeypatch)
        a = MessageBirdAdapter()

        payload = a._build_payload({
            "to": "+15551234567",
            "body": "Your order shipped!",
        })
        assert payload["recipients"] == ["+15551234567"]
        assert payload["body"] == "Your order shipped!"
        assert payload["originator"] == "ShopAI"

    def test_from_number_override(self, monkeypatch):
        from core.adapters.sms.messagebird import MessageBirdAdapter
        _configure_messagebird(monkeypatch)
        a = MessageBirdAdapter()

        payload = a._build_payload({
            "to": "+15551234567",
            "body": "Hello",
            "from_number": "+15559876543",
        })
        assert payload["originator"] == "+15559876543"


class TestMessageBirdSend:
    def test_send_happy_path(self, monkeypatch):
        from core.adapters.sms.messagebird import MessageBirdAdapter
        _configure_messagebird(monkeypatch)
        a = MessageBirdAdapter()

        raw = {
            "id": "msg-abc123",
            "recipients": {
                "totalCount": 1,
                "items": [{"status": "sent"}],
            },
        }

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(
                Capability.SEND_SMS,
                {"to": "+15551234567", "body": "Order shipped!"},
            )

        assert result.ok
        assert result.data["message_id"] == "msg-abc123"
        assert result.data["status"] == "sent"
        assert result.data["segments"] == 1

    def test_send_validation_rejects_bad_number(self, monkeypatch):
        from core.adapters.sms.messagebird import MessageBirdAdapter
        _configure_messagebird(monkeypatch)
        a = MessageBirdAdapter()

        result = a.execute(
            Capability.SEND_SMS,
            {"to": "not-a-number", "body": "Hello"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_send_error_response(self, monkeypatch):
        from core.adapters.sms.messagebird import MessageBirdAdapter
        _configure_messagebird(monkeypatch)
        a = MessageBirdAdapter()

        raw = {"errors": [{"description": "Invalid recipient"}]}

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(
                Capability.SEND_SMS,
                {"to": "+15551234567", "body": "Hello"},
            )

        assert not result.ok


class TestMessageBirdBootstrap:
    def test_register_all_includes_messagebird(self):
        from core.adapters.sms.bootstrap import register_all
        status = register_all()
        assert "messagebird" in status
        assert "twilio" in status

    def test_router_prefers_twilio(self, monkeypatch):
        """Twilio (80) should be preferred over MessageBird (60)."""
        from core.adapters.sms.bootstrap import register_all
        _configure_messagebird(monkeypatch)
        monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
        monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550001111")
        get_config().reload()
        register_all()
        chain = get_router().candidates(Capability.SEND_SMS)
        names = [a.name for a in chain]
        assert names[0] == "twilio"
        assert "messagebird" in names
