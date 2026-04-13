"""Tests for the Klaviyo email adapter.

Real HTTP calls are forbidden — every test patches
``_http_post`` to return canned responses.

Coverage:

  * KlaviyoAdapter metadata (name, category, capabilities,
    priority, free tier limits)
  * is_configured() requires KLAVIYO_API_KEY
  * ``Klaviyo-API-Key`` auth prefix (NOT Bearer)
  * ``revision`` header for API versioning
  * Payload translation (Events API shape with metric, profile,
    properties)
  * Profile first/last name splitting from ``to_name``
  * Metric name: transactional vs campaign
  * Response parsing (empty body → success, error body → raise)
  * Bootstrap registers klaviyo alongside brevo + resend + sendgrid
  * Router preference: Klaviyo(95) > Brevo(90) > Resend(75) > SendGrid(60)
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
        "SENDGRID_API_KEY",
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


def _configure_klaviyo(monkeypatch, *, key="pk_test_abc123"):
    monkeypatch.setenv("KLAVIYO_API_KEY", key)
    get_config().reload()


# ── KlaviyoAdapter metadata ─────────────────────────────


class TestKlaviyoMetadata:
    def test_metadata(self):
        from core.adapters.email.klaviyo import KlaviyoAdapter
        a = KlaviyoAdapter()
        assert a.name == "klaviyo"
        assert a.category == AdapterCategory.EMAIL
        assert Capability.SEND_EMAIL_TRANSACTIONAL in a.capabilities
        assert Capability.SEND_EMAIL_CAMPAIGN in a.capabilities
        assert a.priority == 95
        assert a.free_tier_monthly_limit == 500
        assert a.cost_per_call == 0.0

    def test_base_url(self):
        from core.adapters.email.klaviyo import KlaviyoAdapter
        a = KlaviyoAdapter()
        assert a.base_url == "https://a.klaviyo.com/api"


# ── Configuration ─────────────────────────────────────────


class TestKlaviyoConfiguration:
    def test_unconfigured_without_key(self):
        from core.adapters.email.klaviyo import KlaviyoAdapter
        assert not KlaviyoAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        assert KlaviyoAdapter().is_configured()


# ── Auth headers ──────────────────────────────────────────


class TestKlaviyoAuth:
    def test_uses_klaviyo_api_key_prefix(self, monkeypatch):
        """Klaviyo uses ``Klaviyo-API-Key`` prefix, NOT Bearer."""
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch, key="pk_my_secret")
        a = KlaviyoAdapter()
        headers = a._auth_headers()
        assert headers["Authorization"] == "Klaviyo-API-Key pk_my_secret"
        assert "Bearer" not in headers["Authorization"]

    def test_revision_header_present(self, monkeypatch):
        """Klaviyo API requires a revision header."""
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        a = KlaviyoAdapter()
        headers = a._auth_headers()
        assert "revision" in headers
        assert headers["revision"] == "2024-10-15"

    def test_content_type_json(self, monkeypatch):
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        headers = KlaviyoAdapter()._auth_headers()
        assert headers["Content-Type"] == "application/json"


# ── Payload translation ──────────────────────────────────


class TestKlaviyoPayload:
    def test_send_url_is_events(self, monkeypatch):
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        a = KlaviyoAdapter()
        assert a._send_url() == "https://a.klaviyo.com/api/events"

    def test_payload_structure(self, monkeypatch):
        """Verify the Events API payload shape."""
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        a = KlaviyoAdapter()

        captured = {}
        def fake_post(url, body, headers):
            captured["body"] = body
            return {}  # empty = success

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )

        assert result.ok
        body = captured["body"]

        # Top-level shape
        assert body["data"]["type"] == "event"

        # Metric
        metric = body["data"]["attributes"]["metric"]["data"]
        assert metric["type"] == "metric"
        assert metric["attributes"]["name"] == "ShopAI Transactional Email"

        # Profile
        profile = body["data"]["attributes"]["profile"]["data"]
        assert profile["type"] == "profile"
        assert profile["attributes"]["email"] == "alice@example.com"

        # Properties carry email content
        props = body["data"]["attributes"]["properties"]
        assert props["subject"] == "Your order has shipped"
        assert props["from_email"] == "shop@example.com"
        assert props["from_name"] == "Acme Store"
        assert props["html"] == "<p>Tracking: 9400111899</p>"
        assert props["text"] == "Tracking: 9400111899"

    def test_profile_name_splitting(self, monkeypatch):
        """to_name with space splits into first_name + last_name."""
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        a = KlaviyoAdapter()

        captured = {}
        def fake_post(url, body, headers):
            captured["body"] = body
            return {}

        params = dict(_VALID_MESSAGE)
        params["to_name"] = "Alice Smith"

        with patch.object(a, "_http_post", side_effect=fake_post):
            a.execute(Capability.SEND_EMAIL_TRANSACTIONAL, params)

        profile_attrs = captured["body"]["data"]["attributes"]["profile"]["data"]["attributes"]
        assert profile_attrs["first_name"] == "Alice"
        assert profile_attrs["last_name"] == "Smith"

    def test_profile_single_name(self, monkeypatch):
        """to_name without space → only first_name."""
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        a = KlaviyoAdapter()

        captured = {}
        def fake_post(url, body, headers):
            captured["body"] = body
            return {}

        params = dict(_VALID_MESSAGE)
        params["to_name"] = "Alice"

        with patch.object(a, "_http_post", side_effect=fake_post):
            a.execute(Capability.SEND_EMAIL_TRANSACTIONAL, params)

        profile_attrs = captured["body"]["data"]["attributes"]["profile"]["data"]["attributes"]
        assert profile_attrs["first_name"] == "Alice"
        assert "last_name" not in profile_attrs

    def test_campaign_metric_name(self, monkeypatch):
        """Tags containing 'campaign' switch metric to campaign name."""
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        a = KlaviyoAdapter()

        captured = {}
        def fake_post(url, body, headers):
            captured["body"] = body
            return {}

        params = dict(_VALID_MESSAGE)
        params["tags"] = ["campaign_welcome", "vip"]

        with patch.object(a, "_http_post", side_effect=fake_post):
            a.execute(Capability.SEND_EMAIL_TRANSACTIONAL, params)

        metric_name = captured["body"]["data"]["attributes"]["metric"]["data"]["attributes"]["name"]
        assert metric_name == "ShopAI Campaign Email"

    def test_reply_to_in_properties(self, monkeypatch):
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        a = KlaviyoAdapter()

        captured = {}
        def fake_post(url, body, headers):
            captured["body"] = body
            return {}

        params = dict(_VALID_MESSAGE)
        params["reply_to"] = "support@example.com"

        with patch.object(a, "_http_post", side_effect=fake_post):
            a.execute(Capability.SEND_EMAIL_TRANSACTIONAL, params)

        props = captured["body"]["data"]["attributes"]["properties"]
        assert props["reply_to"] == "support@example.com"


# ── Response parsing ──────────────────────────────────────


class TestKlaviyoResponse:
    def test_empty_body_is_success(self, monkeypatch):
        """Klaviyo returns empty body on 202 — treated as success."""
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        a = KlaviyoAdapter()

        with patch.object(a, "_http_post", return_value={}):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )
        assert result.ok
        assert result.data["message_id"] == "klaviyo-accepted"

    def test_error_body_raises(self, monkeypatch):
        """Klaviyo error responses have ``{"errors": [...]}``."""
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        a = KlaviyoAdapter()

        error_response = {
            "errors": [{"detail": "Invalid API key"}]
        }
        with patch.object(a, "_http_post", return_value=error_response):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterError)
        assert "Invalid API key" in result.error.reason

    def test_response_with_id(self, monkeypatch):
        """If Klaviyo returns an id field, use it."""
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        a = KlaviyoAdapter()

        with patch.object(a, "_http_post", return_value={"id": "evt_abc123"}):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )
        assert result.ok
        assert result.data["message_id"] == "evt_abc123"


# ── Error handling ────────────────────────────────────────


class TestKlaviyoErrors:
    def test_auth_error(self, monkeypatch):
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        a = KlaviyoAdapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterAuthError(a.name, "bad key"),
        ):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterAuthError)

    def test_rate_limit_error(self, monkeypatch):
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        a = KlaviyoAdapter()
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

    def test_validation_missing_to(self, monkeypatch):
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        a = KlaviyoAdapter()
        params = dict(_VALID_MESSAGE)
        del params["to"]
        result = a.execute(Capability.SEND_EMAIL_TRANSACTIONAL, params)
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_campaign_capability(self, monkeypatch):
        from core.adapters.email.klaviyo import KlaviyoAdapter
        _configure_klaviyo(monkeypatch)
        a = KlaviyoAdapter()
        with patch.object(a, "_http_post", return_value={}):
            result = a.execute(
                Capability.SEND_EMAIL_CAMPAIGN,
                dict(_VALID_MESSAGE),
            )
        assert result.ok
        assert result.capability == "send_email_campaign"


# ── Bootstrap + Router ────────────────────────────────────


class TestKlaviyoBootstrap:
    def test_register_all_includes_klaviyo(self):
        from core.adapters.email.bootstrap import register_all
        status = register_all()
        assert "klaviyo" in status

    def test_klaviyo_unconfigured_without_env(self):
        from core.adapters.email.bootstrap import register_all
        status = register_all()
        assert status["klaviyo"] is False

    def test_klaviyo_configured_when_env_set(self, monkeypatch):
        from core.adapters.email.bootstrap import register_all
        _configure_klaviyo(monkeypatch)
        status = register_all()
        assert status["klaviyo"] is True

    def test_klaviyo_wins_over_brevo(self, monkeypatch):
        """Klaviyo priority=95 > Brevo priority=90."""
        from core.adapters.email.bootstrap import register_all
        _configure_klaviyo(monkeypatch)
        monkeypatch.setenv("BREVO_API_KEY", "xkeysib-k")
        get_config().reload()
        register_all()
        chosen = get_router().route(Capability.SEND_EMAIL_TRANSACTIONAL)
        assert chosen.name == "klaviyo"

    def test_fallback_to_brevo_without_klaviyo(self, monkeypatch):
        """Without Klaviyo key, router falls back to Brevo."""
        from core.adapters.email.bootstrap import register_all
        monkeypatch.setenv("BREVO_API_KEY", "xkeysib-k")
        get_config().reload()
        register_all()
        chosen = get_router().route(Capability.SEND_EMAIL_TRANSACTIONAL)
        assert chosen.name == "brevo"
