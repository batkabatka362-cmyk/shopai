"""Tests for Phase 5 email adapters.

Real HTTP calls are forbidden — every test patches
``_http_post`` to return canned responses.

Coverage:

  * EmailBaseAdapter — required-field validation, malformed
    email validation, missing html+text validation
  * BrevoAdapter — ``api-key`` header (not Bearer), payload
    translation, response parsing
  * ResendAdapter — Bearer auth, ``"Name <email>"`` from
    formatting, tag translation
  * Bootstrap — register_all adds both, router picks Brevo
    when both configured (priority 90 > 75)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterAuthError,
    AdapterCategory,
    AdapterRateLimited,
    AdapterResult,
    AdapterUnavailable,
    AdapterValidationError,
    BaseAdapter,
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
        "BREVO_API_KEY", "RESEND_API_KEY",
        "EASYPOST_API_KEY", "SHIPPO_API_KEY",
        "GROQ_API_KEY", "GEMINI_API_KEY",
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


# ── EmailBaseAdapter ────────────────────────────────────────


class TestEmailBaseAdapter:
    def test_missing_to_validates(self, monkeypatch):
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "k")
        get_config().reload()
        a = BrevoAdapter()
        params = dict(_VALID_MESSAGE)
        del params["to"]
        result = a.execute(
            Capability.SEND_EMAIL_TRANSACTIONAL, params,
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "to" in result.error.reason

    def test_missing_subject_validates(self, monkeypatch):
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "k")
        get_config().reload()
        a = BrevoAdapter()
        params = dict(_VALID_MESSAGE)
        del params["subject"]
        result = a.execute(
            Capability.SEND_EMAIL_TRANSACTIONAL, params,
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "subject" in result.error.reason

    def test_missing_from_email_validates(self, monkeypatch):
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "k")
        get_config().reload()
        a = BrevoAdapter()
        params = dict(_VALID_MESSAGE)
        del params["from_email"]
        result = a.execute(
            Capability.SEND_EMAIL_TRANSACTIONAL, params,
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_missing_body_validates(self, monkeypatch):
        """Must supply at least one of html or text."""
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "k")
        get_config().reload()
        a = BrevoAdapter()
        params = dict(_VALID_MESSAGE)
        del params["html"]
        del params["text"]
        result = a.execute(
            Capability.SEND_EMAIL_TRANSACTIONAL, params,
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "html" in result.error.reason or "text" in result.error.reason

    def test_html_only_is_valid(self, monkeypatch):
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "k")
        get_config().reload()
        a = BrevoAdapter()
        params = dict(_VALID_MESSAGE)
        del params["text"]
        with patch.object(a, "_http_post", return_value={"messageId": "m1"}):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL, params,
            )
        assert result.ok

    def test_text_only_is_valid(self, monkeypatch):
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "k")
        get_config().reload()
        a = BrevoAdapter()
        params = dict(_VALID_MESSAGE)
        del params["html"]
        with patch.object(a, "_http_post", return_value={"messageId": "m1"}):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL, params,
            )
        assert result.ok

    def test_malformed_to_email_validates(self, monkeypatch):
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "k")
        get_config().reload()
        a = BrevoAdapter()
        params = dict(_VALID_MESSAGE)
        params["to"] = "not-an-email"
        result = a.execute(
            Capability.SEND_EMAIL_TRANSACTIONAL, params,
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_malformed_from_email_validates(self, monkeypatch):
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "k")
        get_config().reload()
        a = BrevoAdapter()
        params = dict(_VALID_MESSAGE)
        params["from_email"] = "no-at-sign"
        result = a.execute(
            Capability.SEND_EMAIL_TRANSACTIONAL, params,
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── BrevoAdapter ────────────────────────────────────────────


class TestBrevoAdapter:
    def test_metadata(self):
        from core.adapters.email.brevo import BrevoAdapter
        a = BrevoAdapter()
        assert a.name == "brevo"
        assert a.category == AdapterCategory.EMAIL
        assert Capability.SEND_EMAIL_TRANSACTIONAL in a.capabilities
        assert Capability.SEND_EMAIL_CAMPAIGN in a.capabilities
        assert a.priority == 90
        assert a.free_tier_monthly_limit == 9_000
        assert a.free_tier_daily_limit == 300

    def test_unconfigured_without_key(self):
        from core.adapters.email.brevo import BrevoAdapter
        assert not BrevoAdapter().is_configured()

    def test_configured_when_env_set(self, monkeypatch):
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "xkeysib-test")
        get_config().reload()
        assert BrevoAdapter().is_configured()

    def test_uses_api_key_header_not_bearer(self, monkeypatch):
        """Brevo uses custom ``api-key`` header, not Bearer."""
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "xkeysib-abc")
        get_config().reload()
        a = BrevoAdapter()
        headers = a._auth_headers()
        assert headers["api-key"] == "xkeysib-abc"
        assert "Authorization" not in headers

    def test_send_happy_path(self, monkeypatch):
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "xkeysib-k")
        get_config().reload()

        a = BrevoAdapter()
        captured = {}
        def fake_post(url, body, headers):
            captured["url"] = url
            captured["body"] = body
            captured["headers"] = headers
            return {"messageId": "<abc@smtp-relay.brevo.com>"}

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )

        assert result.ok
        assert result.data["message_id"] == "<abc@smtp-relay.brevo.com>"
        assert result.data["to"] == "alice@example.com"
        assert result.data["subject"] == "Your order has shipped"
        # URL is /v3/smtp/email
        assert "/smtp/email" in captured["url"]
        # Verify the payload shape
        assert captured["body"]["sender"]["email"] == "shop@example.com"
        assert captured["body"]["sender"]["name"] == "Acme Store"
        assert captured["body"]["to"][0]["email"] == "alice@example.com"
        assert captured["body"]["subject"] == "Your order has shipped"
        assert captured["body"]["htmlContent"] == "<p>Tracking: 9400111899</p>"
        assert captured["body"]["textContent"] == "Tracking: 9400111899"

    def test_send_with_reply_to_and_tags(self, monkeypatch):
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "k")
        get_config().reload()
        a = BrevoAdapter()

        captured_body = {}
        def fake_post(url, body, headers):
            captured_body.update(body)
            return {"messageId": "<abc>"}

        params = dict(_VALID_MESSAGE)
        params["reply_to"] = "support@example.com"
        params["tags"] = ["shipment_notification", "order_12345"]

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL, params,
            )
        assert result.ok
        assert captured_body["replyTo"]["email"] == "support@example.com"
        assert captured_body["tags"] == ["shipment_notification", "order_12345"]

    def test_send_email_campaign_capability(self, monkeypatch):
        """SEND_EMAIL_CAMPAIGN routes through the same code
        path as SEND_EMAIL_TRANSACTIONAL — vendors don't
        distinguish at the API level."""
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "k")
        get_config().reload()
        a = BrevoAdapter()
        with patch.object(a, "_http_post", return_value={"messageId": "m1"}):
            result = a.execute(
                Capability.SEND_EMAIL_CAMPAIGN,
                dict(_VALID_MESSAGE),
            )
        assert result.ok
        assert result.capability == "send_email_campaign"

    def test_auth_error_mapped(self, monkeypatch):
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "k")
        get_config().reload()
        a = BrevoAdapter()
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

    def test_rate_limit_mapped(self, monkeypatch):
        from core.adapters.email.brevo import BrevoAdapter
        monkeypatch.setenv("BREVO_API_KEY", "k")
        get_config().reload()
        a = BrevoAdapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterRateLimited(a.name, "too many"),
        ):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterRateLimited)


# ── ResendAdapter ───────────────────────────────────────────


class TestResendAdapter:
    def test_metadata(self):
        from core.adapters.email.resend import ResendAdapter
        a = ResendAdapter()
        assert a.name == "resend"
        assert a.priority == 75  # below Brevo (90)
        assert a.free_tier_monthly_limit == 3_000
        assert a.free_tier_daily_limit == 100

    def test_uses_bearer_auth(self, monkeypatch):
        from core.adapters.email.resend import ResendAdapter
        monkeypatch.setenv("RESEND_API_KEY", "re_abc123")
        get_config().reload()
        a = ResendAdapter()
        headers = a._auth_headers()
        assert headers["Authorization"] == "Bearer re_abc123"

    def test_from_formatted_with_name(self, monkeypatch):
        """Resend accepts ``"Name <email@example.com>"`` or
        plain email. Adapter formats the display name when
        provided."""
        from core.adapters.email.resend import ResendAdapter
        monkeypatch.setenv("RESEND_API_KEY", "re_k")
        get_config().reload()
        a = ResendAdapter()

        captured_body = {}
        def fake_post(url, body, headers):
            captured_body.update(body)
            return {"id": "email_abc"}

        with patch.object(a, "_http_post", side_effect=fake_post):
            a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )

        assert captured_body["from"] == "Acme Store <shop@example.com>"

    def test_from_plain_without_name(self, monkeypatch):
        from core.adapters.email.resend import ResendAdapter
        monkeypatch.setenv("RESEND_API_KEY", "re_k")
        get_config().reload()
        a = ResendAdapter()

        captured_body = {}
        def fake_post(url, body, headers):
            captured_body.update(body)
            return {"id": "email_abc"}

        params = dict(_VALID_MESSAGE)
        del params["from_name"]

        with patch.object(a, "_http_post", side_effect=fake_post):
            a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL, params,
            )

        assert captured_body["from"] == "shop@example.com"

    def test_to_is_array(self, monkeypatch):
        """Resend expects ``to`` as an array, even for single
        recipient."""
        from core.adapters.email.resend import ResendAdapter
        monkeypatch.setenv("RESEND_API_KEY", "re_k")
        get_config().reload()
        a = ResendAdapter()

        captured_body = {}
        def fake_post(url, body, headers):
            captured_body.update(body)
            return {"id": "email_abc"}

        with patch.object(a, "_http_post", side_effect=fake_post):
            a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )

        assert captured_body["to"] == ["alice@example.com"]

    def test_tags_translated_to_resend_shape(self, monkeypatch):
        """Resend wants tags as ``[{"name": ..., "value": ...}]``."""
        from core.adapters.email.resend import ResendAdapter
        monkeypatch.setenv("RESEND_API_KEY", "re_k")
        get_config().reload()
        a = ResendAdapter()

        captured_body = {}
        def fake_post(url, body, headers):
            captured_body.update(body)
            return {"id": "x"}

        params = dict(_VALID_MESSAGE)
        params["tags"] = ["welcome", "vip"]

        with patch.object(a, "_http_post", side_effect=fake_post):
            a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL, params,
            )

        assert captured_body["tags"] == [
            {"name": "category", "value": "welcome"},
            {"name": "category", "value": "vip"},
        ]

    def test_parse_response_extracts_id(self, monkeypatch):
        from core.adapters.email.resend import ResendAdapter
        monkeypatch.setenv("RESEND_API_KEY", "k")
        get_config().reload()
        a = ResendAdapter()
        with patch.object(a, "_http_post", return_value={
            "id": "email_abc123",
        }):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL,
                dict(_VALID_MESSAGE),
            )
        assert result.ok
        assert result.data["message_id"] == "email_abc123"


# ── Bootstrap + Router selection ────────────────────────────


class TestEmailBootstrap:
    def test_register_all_adds_both_adapters(self):
        from core.adapters.email.bootstrap import register_all
        status = register_all()
        assert set(status.keys()) == {"brevo", "resend"}

    def test_neither_configured_without_keys(self):
        from core.adapters.email.bootstrap import register_all
        status = register_all()
        assert status["brevo"] is False
        assert status["resend"] is False

    def test_register_all_idempotent(self):
        from core.adapters.email.bootstrap import register_all
        register_all()
        register_all()
        assert len(get_registry()) == 2

    def test_router_picks_brevo_when_both_configured(self, monkeypatch):
        from core.adapters.email.bootstrap import register_all
        monkeypatch.setenv("BREVO_API_KEY", "k")
        monkeypatch.setenv("RESEND_API_KEY", "k")
        get_config().reload()
        register_all()
        chosen = get_router().route(Capability.SEND_EMAIL_TRANSACTIONAL)
        assert chosen.name == "brevo"  # priority 90 > 75

    def test_router_falls_back_to_resend(self, monkeypatch):
        from core.adapters.email.bootstrap import register_all
        monkeypatch.setenv("RESEND_API_KEY", "k")
        get_config().reload()
        register_all()
        chosen = get_router().route(Capability.SEND_EMAIL_TRANSACTIONAL)
        assert chosen.name == "resend"

    def test_router_raises_when_none_configured(self):
        from core.adapters.email.bootstrap import register_all
        from core.adapters import NoAdapterAvailable
        register_all()
        with pytest.raises(NoAdapterAvailable):
            get_router().route(Capability.SEND_EMAIL_TRANSACTIONAL)

    def test_campaign_capability_also_resolves(self, monkeypatch):
        """SEND_EMAIL_CAMPAIGN is served by the same adapters
        (same router chain), not a separate pool."""
        from core.adapters.email.bootstrap import register_all
        monkeypatch.setenv("BREVO_API_KEY", "k")
        get_config().reload()
        register_all()
        chosen = get_router().route(Capability.SEND_EMAIL_CAMPAIGN)
        assert chosen.name == "brevo"
