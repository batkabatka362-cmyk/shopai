"""Tests for the SendGrid email adapter.

Mirrors the Brevo/Resend test structure. Real HTTP calls are
forbidden — every test patches ``_http_post`` to return canned
responses.

Coverage:

  * SendGridAdapter metadata (name, category, capabilities,
    priority, free tier)
  * is_configured() requires SENDGRID_API_KEY
  * Bearer auth (inherited from EmailBaseAdapter)
  * Payload translation (personalizations, content array, etc.)
  * Response parsing (empty body on 202, error body)
  * Bootstrap registers sendgrid alongside brevo + resend
  * Router preference: Brevo(90) > Resend(75) > SendGrid(60)
  * Router fallback: SendGrid used when Brevo + Resend absent
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterAuthError,
    AdapterCategory,
    AdapterRateLimited,
    AdapterValidationError,
    Capability,
    get_config,
    get_metrics,
    get_registry,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)
from core.adapters.errors import AdapterError


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "BREVO_API_KEY", "KLAVIYO_API_KEY", "RESEND_API_KEY",
        "SENDGRID_API_KEY", "EASYPOST_API_KEY", "SHIPPO_API_KEY",
    ):
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


_VALID_MESSAGE = {
    "to": "alice@example.com",
    "from_email": "shop@example.com",
    "from_name": "Acme Store",
    "subject": "Your order has shipped",
    "html": "<p>Tracking: 9400111899</p>",
    "text": "Tracking: 9400111899",
}


def _configure_sendgrid(monkeypatch, *, key="SG.test-key-abc"):
    monkeypatch.setenv("SENDGRID_API_KEY", key)
    get_config().reload()


# ── SendGridAdapter metadata ──────────────────────────────


class TestSendGridMetadata:
    def test_metadata(self):
        from core.adapters.email.sendgrid import SendGridAdapter
        a = SendGridAdapter()
        assert a.name == "sendgrid"
        assert a.category == AdapterCategory.EMAIL
        assert Capability.SEND_EMAIL_TRANSACTIONAL in a.capabilities
        assert Capability.SEND_EMAIL_CAMPAIGN in a.capabilities
        assert a.priority == 60
        assert a.free_tier_daily_limit == 100
        assert a.free_tier_monthly_limit == 3_000


# ── Configuration ──────────────────────────────────────────


class TestSendGridConfiguration:
    def test_unconfigured_without_key(self):
        from core.adapters.email.sendgrid import SendGridAdapter
        assert not SendGridAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.email.sendgrid import SendGridAdapter
        _configure_sendgrid(monkeypatch)
        assert SendGridAdapter().is_configured()

    def test_uses_bearer_auth(self, monkeypatch):
        from core.adapters.email.sendgrid import SendGridAdapter
        _configure_sendgrid(monkeypatch, key="SG.my-key")
        a = SendGridAdapter()
        headers = a._auth_headers()
        assert headers["Authorization"] == "Bearer SG.my-key"


# ── Send happy path ───────────────────────────────────────


class TestSendGridSend:
    def test_send_happy_path(self, monkeypatch):
        from core.adapters.email.sendgrid import SendGridAdapter
        _configure_sendgrid(monkeypatch)
        a = SendGridAdapter()

        captured = {}

        def fake_post(url, body, headers):
            captured["url"] = url
            captured["body"] = body
            captured["headers"] = headers
            return {}  # SendGrid returns empty body on 202

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )

        assert result.ok
        assert result.data["message_id"] == "sendgrid-accepted"
        assert result.data["to"] == "alice@example.com"
        assert result.data["subject"] == "Your order has shipped"

        # URL is /v3/mail/send
        assert "/mail/send" in captured["url"]

        # Verify personalizations structure
        body = captured["body"]
        assert body["personalizations"][0]["to"][0]["email"] == "alice@example.com"
        assert body["from"]["email"] == "shop@example.com"
        assert body["from"]["name"] == "Acme Store"
        assert body["subject"] == "Your order has shipped"

        # Content array — text first, then html
        assert len(body["content"]) == 2
        assert body["content"][0]["type"] == "text/plain"
        assert body["content"][0]["value"] == "Tracking: 9400111899"
        assert body["content"][1]["type"] == "text/html"
        assert body["content"][1]["value"] == "<p>Tracking: 9400111899</p>"

    def test_send_with_reply_to_and_tags(self, monkeypatch):
        from core.adapters.email.sendgrid import SendGridAdapter
        _configure_sendgrid(monkeypatch)
        a = SendGridAdapter()

        captured_body = {}

        def fake_post(url, body, headers):
            captured_body.update(body)
            return {}

        params = dict(_VALID_MESSAGE)
        params["reply_to"] = "support@example.com"
        params["tags"] = ["shipment", "order_12345"]

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL, params,
            )

        assert result.ok
        assert captured_body["reply_to"]["email"] == "support@example.com"
        assert captured_body["categories"] == ["shipment", "order_12345"]

    def test_send_with_to_name(self, monkeypatch):
        from core.adapters.email.sendgrid import SendGridAdapter
        _configure_sendgrid(monkeypatch)
        a = SendGridAdapter()

        captured_body = {}

        def fake_post(url, body, headers):
            captured_body.update(body)
            return {}

        params = dict(_VALID_MESSAGE)
        params["to_name"] = "Alice Smith"

        with patch.object(a, "_http_post", side_effect=fake_post):
            a.execute(Capability.SEND_EMAIL_TRANSACTIONAL, params)

        to_entry = captured_body["personalizations"][0]["to"][0]
        assert to_entry["email"] == "alice@example.com"
        assert to_entry["name"] == "Alice Smith"

    def test_html_only(self, monkeypatch):
        from core.adapters.email.sendgrid import SendGridAdapter
        _configure_sendgrid(monkeypatch)
        a = SendGridAdapter()

        captured_body = {}

        def fake_post(url, body, headers):
            captured_body.update(body)
            return {}

        params = dict(_VALID_MESSAGE)
        del params["text"]

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(Capability.SEND_EMAIL_TRANSACTIONAL, params)

        assert result.ok
        assert len(captured_body["content"]) == 1
        assert captured_body["content"][0]["type"] == "text/html"

    def test_text_only(self, monkeypatch):
        from core.adapters.email.sendgrid import SendGridAdapter
        _configure_sendgrid(monkeypatch)
        a = SendGridAdapter()

        captured_body = {}

        def fake_post(url, body, headers):
            captured_body.update(body)
            return {}

        params = dict(_VALID_MESSAGE)
        del params["html"]

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(Capability.SEND_EMAIL_TRANSACTIONAL, params)

        assert result.ok
        assert len(captured_body["content"]) == 1
        assert captured_body["content"][0]["type"] == "text/plain"

    def test_campaign_capability(self, monkeypatch):
        from core.adapters.email.sendgrid import SendGridAdapter
        _configure_sendgrid(monkeypatch)
        a = SendGridAdapter()
        with patch.object(a, "_http_post", return_value={}):
            result = a.execute(
                Capability.SEND_EMAIL_CAMPAIGN,
                dict(_VALID_MESSAGE),
            )
        assert result.ok
        assert result.capability == "send_email_campaign"


# ── Error handling ─────────────────────────────────────────


class TestSendGridErrors:
    def test_auth_error(self, monkeypatch):
        from core.adapters.email.sendgrid import SendGridAdapter
        _configure_sendgrid(monkeypatch)
        a = SendGridAdapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterAuthError(a.name, "invalid key"),
        ):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterAuthError)

    def test_rate_limit_error(self, monkeypatch):
        from core.adapters.email.sendgrid import SendGridAdapter
        _configure_sendgrid(monkeypatch)
        a = SendGridAdapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterRateLimited(a.name, "429"),
        ):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterRateLimited)

    def test_sendgrid_error_body_raises(self, monkeypatch):
        """SendGrid error responses with errors array raise AdapterError."""
        from core.adapters.email.sendgrid import SendGridAdapter
        _configure_sendgrid(monkeypatch)
        a = SendGridAdapter()
        error_response = {
            "errors": [{"message": "The from address does not match a verified Sender Identity."}]
        }
        with patch.object(a, "_http_post", return_value=error_response):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterError)

    def test_validation_missing_to(self, monkeypatch):
        from core.adapters.email.sendgrid import SendGridAdapter
        _configure_sendgrid(monkeypatch)
        a = SendGridAdapter()
        params = dict(_VALID_MESSAGE)
        del params["to"]
        result = a.execute(Capability.SEND_EMAIL_TRANSACTIONAL, params)
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── Bootstrap ──────────────────────────────────────────────


class TestSendGridBootstrap:
    def test_register_all_adds_sendgrid(self):
        from core.adapters.email.bootstrap import register_all
        status = register_all()
        assert "sendgrid" in status
        assert "brevo" in status
        assert "resend" in status

    def test_sendgrid_unconfigured_without_env(self):
        from core.adapters.email.bootstrap import register_all
        status = register_all()
        assert status["sendgrid"] is False

    def test_sendgrid_configured_when_env_set(self, monkeypatch):
        from core.adapters.email.bootstrap import register_all
        _configure_sendgrid(monkeypatch)
        status = register_all()
        assert status["sendgrid"] is True

    def test_register_all_idempotent(self):
        from core.adapters.email.bootstrap import register_all
        register_all()
        register_all()
        assert len([n for n in get_registry().names() if n == "sendgrid"]) == 1


# ── Router integration ─────────────────────────────────────


class TestSendGridRouterIntegration:
    def test_router_routes_to_sendgrid_when_only_one(self, monkeypatch):
        from core.adapters.email.bootstrap import register_all
        _configure_sendgrid(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.SEND_EMAIL_TRANSACTIONAL)
        assert chosen.name == "sendgrid"

    def test_brevo_wins_over_sendgrid(self, monkeypatch):
        """Brevo priority=90 > SendGrid priority=60."""
        from core.adapters.email.bootstrap import register_all
        _configure_sendgrid(monkeypatch)
        monkeypatch.setenv("BREVO_API_KEY", "xkeysib-k")
        get_config().reload()
        register_all()
        chosen = get_router().route(Capability.SEND_EMAIL_TRANSACTIONAL)
        assert chosen.name == "brevo"

    def test_resend_wins_over_sendgrid(self, monkeypatch):
        """Resend priority=75 > SendGrid priority=60."""
        from core.adapters.email.bootstrap import register_all
        _configure_sendgrid(monkeypatch)
        monkeypatch.setenv("RESEND_API_KEY", "re_k")
        get_config().reload()
        register_all()
        chosen = get_router().route(Capability.SEND_EMAIL_TRANSACTIONAL)
        assert chosen.name == "resend"

    def test_end_to_end_metrics(self, monkeypatch):
        from core.adapters.email.bootstrap import register_all
        from core.adapters.email.sendgrid import SendGridAdapter

        _configure_sendgrid(monkeypatch)
        register_all()

        adapter = get_registry().get("sendgrid")
        assert isinstance(adapter, SendGridAdapter)

        with patch.object(adapter, "_http_post", return_value={}):
            result = get_router().execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )

        assert result.ok
        assert result.adapter == "sendgrid"

        stats = get_metrics().stats_for("sendgrid")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_success"] == 1
