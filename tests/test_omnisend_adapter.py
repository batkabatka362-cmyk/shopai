"""Tests for the Omnisend email adapter.

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
    monkeypatch.delenv("OMNISEND_API_KEY", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_omnisend(monkeypatch, *, key="os-test-key"):
    monkeypatch.setenv("OMNISEND_API_KEY", key)
    get_config().reload()


def _valid_message():
    return {
        "to": "customer@example.com",
        "from_email": "shop@example.com",
        "subject": "Welcome!",
        "html": "<p>Welcome to our store</p>",
    }


class TestOmnisendMetadata:
    def test_metadata(self):
        from core.adapters.email.omnisend import OmnisendAdapter
        a = OmnisendAdapter()
        assert a.name == "omnisend"
        assert a.category == AdapterCategory.EMAIL
        assert Capability.SEND_EMAIL_TRANSACTIONAL in a.capabilities
        assert a.priority == 65

    def test_unconfigured_without_key(self):
        from core.adapters.email.omnisend import OmnisendAdapter
        assert not OmnisendAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.email.omnisend import OmnisendAdapter
        _configure_omnisend(monkeypatch)
        assert OmnisendAdapter().is_configured()


class TestOmnisendAuth:
    def test_auth_header(self, monkeypatch):
        from core.adapters.email.omnisend import OmnisendAdapter
        _configure_omnisend(monkeypatch, key="my-api-key")
        a = OmnisendAdapter()
        headers = a._auth_headers()
        assert headers["X-API-KEY"] == "my-api-key"


class TestOmnisendPayload:
    def test_basic_payload(self, monkeypatch):
        from core.adapters.email.omnisend import OmnisendAdapter
        _configure_omnisend(monkeypatch)
        a = OmnisendAdapter()

        payload = a._build_payload(_valid_message())
        assert payload["email"] == "customer@example.com"
        assert payload["eventName"] == "transactional"
        assert payload["fields"]["subject"] == "Welcome!"
        assert payload["fields"]["fromEmail"] == "shop@example.com"

    def test_tags_included(self, monkeypatch):
        from core.adapters.email.omnisend import OmnisendAdapter
        _configure_omnisend(monkeypatch)
        a = OmnisendAdapter()

        msg = {**_valid_message(), "tags": ["welcome", "onboarding"]}
        payload = a._build_payload(msg)
        assert payload["tags"] == ["welcome", "onboarding"]


class TestOmnisendSend:
    def test_send_happy_path(self, monkeypatch):
        from core.adapters.email.omnisend import OmnisendAdapter
        _configure_omnisend(monkeypatch)
        a = OmnisendAdapter()

        raw = {"eventID": "evt-123"}

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                _valid_message(),
            )

        assert result.ok
        assert result.data["message_id"] == "evt-123"

    def test_send_error_response(self, monkeypatch):
        from core.adapters.email.omnisend import OmnisendAdapter
        _configure_omnisend(monkeypatch)
        a = OmnisendAdapter()

        raw = {"error": "Invalid API key"}

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                _valid_message(),
            )

        assert not result.ok


class TestOmnisendBootstrap:
    def test_register_all_includes_omnisend(self):
        from core.adapters.email.bootstrap import register_all
        status = register_all()
        assert "omnisend" in status
