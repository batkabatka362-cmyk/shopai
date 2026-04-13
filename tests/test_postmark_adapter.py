"""Tests for the Postmark email adapter.

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
    monkeypatch.delenv("POSTMARK_SERVER_TOKEN", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_postmark(monkeypatch, *, key="pm-test-token"):
    monkeypatch.setenv("POSTMARK_SERVER_TOKEN", key)
    get_config().reload()


def _valid_message():
    return {
        "to": "customer@example.com",
        "from_email": "shop@example.com",
        "subject": "Order shipped",
        "html": "<p>Your order shipped!</p>",
    }


class TestPostmarkMetadata:
    def test_metadata(self):
        from core.adapters.email.postmark import PostmarkAdapter
        a = PostmarkAdapter()
        assert a.name == "postmark"
        assert a.category == AdapterCategory.EMAIL
        assert Capability.SEND_EMAIL_TRANSACTIONAL in a.capabilities
        assert a.priority == 70

    def test_unconfigured_without_key(self):
        from core.adapters.email.postmark import PostmarkAdapter
        assert not PostmarkAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.email.postmark import PostmarkAdapter
        _configure_postmark(monkeypatch)
        assert PostmarkAdapter().is_configured()


class TestPostmarkAuth:
    def test_auth_header(self, monkeypatch):
        from core.adapters.email.postmark import PostmarkAdapter
        _configure_postmark(monkeypatch, key="my-server-token")
        a = PostmarkAdapter()
        headers = a._auth_headers()
        assert headers["X-Postmark-Server-Token"] == "my-server-token"


class TestPostmarkPayload:
    def test_basic_payload(self, monkeypatch):
        from core.adapters.email.postmark import PostmarkAdapter
        _configure_postmark(monkeypatch)
        a = PostmarkAdapter()

        msg = _valid_message()
        payload = a._build_payload(msg)
        assert payload["From"] == "shop@example.com"
        assert payload["To"] == "customer@example.com"
        assert payload["Subject"] == "Order shipped"
        assert payload["HtmlBody"] == "<p>Your order shipped!</p>"

    def test_from_name_included(self, monkeypatch):
        from core.adapters.email.postmark import PostmarkAdapter
        _configure_postmark(monkeypatch)
        a = PostmarkAdapter()

        msg = {**_valid_message(), "from_name": "Acme Store"}
        payload = a._build_payload(msg)
        assert payload["From"] == "Acme Store <shop@example.com>"

    def test_tag_included(self, monkeypatch):
        from core.adapters.email.postmark import PostmarkAdapter
        _configure_postmark(monkeypatch)
        a = PostmarkAdapter()

        msg = {**_valid_message(), "tags": ["shipping"]}
        payload = a._build_payload(msg)
        assert payload["Tag"] == "shipping"


class TestPostmarkSend:
    def test_send_happy_path(self, monkeypatch):
        from core.adapters.email.postmark import PostmarkAdapter
        _configure_postmark(monkeypatch)
        a = PostmarkAdapter()

        raw = {"MessageID": "abc-123", "ErrorCode": 0}

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                _valid_message(),
            )

        assert result.ok
        assert result.data["message_id"] == "abc-123"
        assert result.data["to"] == "customer@example.com"

    def test_send_error_response(self, monkeypatch):
        from core.adapters.email.postmark import PostmarkAdapter
        _configure_postmark(monkeypatch)
        a = PostmarkAdapter()

        raw = {"ErrorCode": 300, "Message": "Invalid email"}

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                _valid_message(),
            )

        assert not result.ok

    def test_send_missing_fields_rejected(self, monkeypatch):
        from core.adapters.email.postmark import PostmarkAdapter
        _configure_postmark(monkeypatch)
        a = PostmarkAdapter()

        result = a.execute(
            Capability.SEND_EMAIL_TRANSACTIONAL,
            {"to": "a@b.com"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


class TestPostmarkBootstrap:
    def test_register_all_includes_postmark(self):
        from core.adapters.email.bootstrap import register_all
        status = register_all()
        assert "postmark" in status
