"""Regression tests for the SMS adapter family.

Wave 1 extension — Twilio only.

Real HTTP calls are forbidden — every test patches the adapter's
``_http_post`` helper so the suite stays hermetic.

Coverage matrix:

  * Capability enum exposes SEND_SMS
  * SmsBaseAdapter validates inputs (to/body required, E.164
    format, body length, from_number override format) and
    rejects unknown capabilities
  * TwilioAdapter
        - registry metadata (name, category, capabilities,
          priority, cost)
        - is_configured() requires Account SID + Auth Token +
          From number
        - _send_url embeds the Account SID
        - _auth_headers use Basic auth with base64(sid:token)
        - form payload: To / From / Body / MediaUrl
        - per-call from_number override
        - segment estimation fallback when vendor response lacks
          ``num_segments``
        - happy path: message_id + segments captured from response
        - HTTP error mapping (auth, rate limit)
  * Bootstrap
        - register_all adds the adapter, idempotent
        - status map reflects is_configured
  * SmartRouter
        - routes SEND_SMS to twilio when configured
        - raises NoAdapterAvailable when unconfigured
        - end-to-end execute() succeeds and the metrics collector
          captures the outcome INCLUDING cost_usd scaled by
          segment count
"""
from __future__ import annotations

import base64
from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterAuthError,
    AdapterCategory,
    AdapterRateLimited,
    AdapterValidationError,
    Capability,
    NoAdapterAvailable,
    get_config,
    get_metrics,
    get_registry,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Clear Twilio env + every adapter singleton between tests."""
    for var in (
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
        "BREVO_API_KEY",
        "RESEND_API_KEY",
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
        "OPENAI_API_KEY",
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


_ACCOUNT_SID = "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
_AUTH_TOKEN = "authtoken0123456789abcdef"
_FROM_NUMBER = "+15559876543"


def _configure_twilio(monkeypatch) -> None:
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", _ACCOUNT_SID)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", _AUTH_TOKEN)
    monkeypatch.setenv("TWILIO_FROM_NUMBER", _FROM_NUMBER)
    get_config().reload()


_VALID_SMS = {
    "to": "+15551234567",
    "body": "Your order #1001 has shipped.",
}


# ── Capability enum ─────────────────────────────────────────


class TestSmsCapabilities:
    def test_send_sms_capability_exists(self):
        assert Capability("send_sms") is Capability.SEND_SMS


# ── SmsBaseAdapter validation ───────────────────────────────


class TestSmsBaseAdapter:
    def test_to_is_required(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()
        result = a.execute(
            Capability.SEND_SMS, {"body": "hi"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "'to'" in result.error.reason

    def test_to_must_be_e164(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()
        result = a.execute(
            Capability.SEND_SMS,
            {"to": "5551234567", "body": "hi"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "E.164" in result.error.reason

    def test_body_is_required(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()
        result = a.execute(
            Capability.SEND_SMS, {"to": "+15551234567"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "'body'" in result.error.reason

    def test_body_too_long_rejected(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()
        result = a.execute(
            Capability.SEND_SMS,
            {"to": "+15551234567", "body": "x" * 1_601},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "too long" in result.error.reason

    def test_from_number_override_must_be_e164(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()
        result = a.execute(
            Capability.SEND_SMS,
            {
                "to": "+15551234567",
                "body": "hi",
                "from_number": "not-a-number",
            },
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_unknown_capability_returns_validation_error(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()
        result = a.execute(Capability.SEND_EMAIL_TRANSACTIONAL, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── TwilioAdapter ───────────────────────────────────────────


class TestTwilioAdapter:
    def test_metadata(self):
        from core.adapters.sms.twilio import TwilioAdapter
        a = TwilioAdapter()
        assert a.name == "twilio"
        assert a.category == AdapterCategory.SMS
        assert Capability.SEND_SMS in a.capabilities
        assert a.priority == 80
        assert a.cost_per_call == 0.0079

    def test_unconfigured_without_env(self):
        from core.adapters.sms.twilio import TwilioAdapter
        assert not TwilioAdapter().is_configured()

    def test_unconfigured_without_from_number(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        monkeypatch.setenv("TWILIO_ACCOUNT_SID", _ACCOUNT_SID)
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", _AUTH_TOKEN)
        get_config().reload()
        # Missing TWILIO_FROM_NUMBER — not configured even though
        # creds are set, because send always needs a from.
        assert not TwilioAdapter().is_configured()

    def test_configured_with_full_env(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        assert TwilioAdapter().is_configured()

    def test_send_url_embeds_account_sid(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()
        url = a._send_url()
        assert _ACCOUNT_SID in url
        assert url.endswith("/Messages.json")
        assert "api.twilio.com" in url

    def test_auth_headers_use_basic_auth(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()
        headers = a._auth_headers()
        expected = base64.b64encode(
            f"{_ACCOUNT_SID}:{_AUTH_TOKEN}".encode("utf-8"),
        ).decode("ascii")
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["Content-Type"] == "application/x-www-form-urlencoded"

    def test_payload_uses_tenant_from_number(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()
        form = a._build_payload(dict(_VALID_SMS))
        assert form["To"] == "+15551234567"
        assert form["From"] == _FROM_NUMBER
        assert form["Body"] == _VALID_SMS["body"]

    def test_payload_per_call_from_number_overrides(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()
        form = a._build_payload({
            **_VALID_SMS,
            "from_number": "+15550000000",
        })
        assert form["From"] == "+15550000000"

    def test_payload_media_urls_emitted(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()
        form = a._build_payload({
            **_VALID_SMS,
            "media_urls": [
                "https://cdn.example.com/1.jpg",
                "https://cdn.example.com/2.jpg",
            ],
        })
        assert form["MediaUrl"] == [
            "https://cdn.example.com/1.jpg",
            "https://cdn.example.com/2.jpg",
        ]

    def test_estimate_segments_short_body(self):
        from core.adapters.sms.twilio import TwilioAdapter
        assert TwilioAdapter._estimate_segments("hi") == 1
        assert TwilioAdapter._estimate_segments("x" * 160) == 1

    def test_estimate_segments_multi_segment(self):
        from core.adapters.sms.twilio import TwilioAdapter
        # 161 chars → needs 2 concatenated segments
        assert TwilioAdapter._estimate_segments("x" * 161) == 2
        # 307 chars → ceil(307/153) = 3
        assert TwilioAdapter._estimate_segments("x" * 307) == 3


# ── Send happy path ─────────────────────────────────────────


class TestTwilioSend:
    def test_send_happy_path(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()

        captured = {}

        def fake_post(url, body, headers):
            captured["url"] = url
            captured["body"] = body
            captured["headers"] = headers
            return {
                "sid": "SM1234567890abcdef",
                "to": "+15551234567",
                "from": _FROM_NUMBER,
                "status": "queued",
                "num_segments": "1",
            }

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(Capability.SEND_SMS, dict(_VALID_SMS))

        assert result.ok
        assert result.data["message_id"] == "SM1234567890abcdef"
        assert result.data["to"] == "+15551234567"
        assert result.data["status"] == "queued"
        assert result.data["segments"] == 1
        assert result.cost_usd == pytest.approx(0.0079)

        assert _ACCOUNT_SID in captured["url"]
        assert captured["body"]["To"] == "+15551234567"
        assert captured["body"]["From"] == _FROM_NUMBER
        assert captured["body"]["Body"] == _VALID_SMS["body"]
        assert captured["headers"]["Content-Type"] == (
            "application/x-www-form-urlencoded"
        )

    def test_send_multi_segment_cost_scales(self, monkeypatch):
        """A 3-segment response should charge 3x the per-call cost."""
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()

        def fake_post(url, body, headers):
            return {
                "sid": "SM3SEG",
                "to": "+15551234567",
                "status": "queued",
                "num_segments": "3",
            }

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.SEND_SMS,
                {"to": "+15551234567", "body": "x" * 300},
            )

        assert result.ok
        assert result.data["segments"] == 3
        assert result.cost_usd == pytest.approx(0.0079 * 3)

    def test_send_missing_num_segments_falls_back_to_estimate(
        self, monkeypatch,
    ):
        """When Twilio's response lacks ``num_segments`` we estimate
        from body length so cost tracking never silently defaults
        to 0 or 1 for a long body."""
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()

        def fake_post(url, body, headers):
            return {"sid": "SMEST", "status": "queued"}

        long_body = "x" * 400  # ~3 segments
        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.SEND_SMS,
                {"to": "+15551234567", "body": long_body},
            )

        assert result.ok
        assert result.data["segments"] == 3

    def test_send_auth_error_mapped(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterAuthError(a.name, "bad sid"),
        ):
            result = a.execute(Capability.SEND_SMS, dict(_VALID_SMS))
        assert not result.ok
        assert isinstance(result.error, AdapterAuthError)

    def test_send_rate_limit_mapped(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterRateLimited(a.name, "throttled"),
        ):
            result = a.execute(Capability.SEND_SMS, dict(_VALID_SMS))
        assert not result.ok
        assert isinstance(result.error, AdapterRateLimited)

    def test_send_non_dict_response_raises(self, monkeypatch):
        from core.adapters.sms.twilio import TwilioAdapter
        from core.adapters.errors import AdapterError
        _configure_twilio(monkeypatch)
        a = TwilioAdapter()
        with patch.object(a, "_http_post", return_value="unexpected"):
            result = a.execute(Capability.SEND_SMS, dict(_VALID_SMS))
        assert not result.ok
        assert isinstance(result.error, AdapterError)


# ── Bootstrap ───────────────────────────────────────────────


class TestSmsBootstrap:
    def test_register_all_adds_twilio(self):
        from core.adapters.sms.bootstrap import register_all
        status = register_all()
        assert "twilio" in status

    def test_register_all_unconfigured_without_env(self):
        from core.adapters.sms.bootstrap import register_all
        status = register_all()
        assert status["twilio"] is False

    def test_register_all_configured_when_env_set(self, monkeypatch):
        from core.adapters.sms.bootstrap import register_all
        _configure_twilio(monkeypatch)
        status = register_all()
        assert status["twilio"] is True

    def test_register_all_idempotent(self):
        from core.adapters.sms.bootstrap import register_all
        register_all()
        register_all()
        assert len([
            n for n in get_registry().names() if n == "twilio"
        ]) == 1


# ── Smart router routing + metrics capture ──────────────────


class TestSmsRouterIntegration:
    def test_router_routes_send_sms_to_twilio(self, monkeypatch):
        from core.adapters.sms.bootstrap import register_all
        _configure_twilio(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.SEND_SMS)
        assert chosen.name == "twilio"

    def test_router_raises_when_twilio_unconfigured(self):
        from core.adapters.sms.bootstrap import register_all
        register_all()
        with pytest.raises(NoAdapterAvailable):
            get_router().route(Capability.SEND_SMS)

    def test_end_to_end_send_records_metrics(self, monkeypatch):
        """Wave 1 success criterion — the router reaches a brand-new
        external system AND MetricsCollector captures the outcome,
        INCLUDING cost_usd scaled by the vendor's segment count."""
        from core.adapters.sms.bootstrap import register_all
        from core.adapters.sms.twilio import TwilioAdapter

        _configure_twilio(monkeypatch)
        register_all()

        adapter = get_registry().get("twilio")
        assert isinstance(adapter, TwilioAdapter)

        def fake_post(url, body, headers):
            return {
                "sid": "SM1234567890abcdef",
                "to": "+15551234567",
                "status": "queued",
                "num_segments": "1",
            }

        with patch.object(adapter, "_http_post", side_effect=fake_post):
            result = get_router().execute(
                Capability.SEND_SMS, dict(_VALID_SMS),
            )

        assert result.ok
        assert result.adapter == "twilio"
        assert result.capability == "send_sms"
        assert result.data["message_id"] == "SM1234567890abcdef"
        assert result.cost_usd == pytest.approx(0.0079)

        stats = get_metrics().stats_for("twilio")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_success"] == 1
        assert stats["calls_failure"] == 0
        assert stats["success_rate"] == 1.0

    def test_router_records_failure_metric(self, monkeypatch):
        """A failed call must still flow into the metrics layer so
        the router's success-rate EMA degrades."""
        from core.adapters.sms.bootstrap import register_all
        from core.adapters.sms.twilio import TwilioAdapter

        _configure_twilio(monkeypatch)
        register_all()
        adapter = get_registry().get("twilio")
        assert isinstance(adapter, TwilioAdapter)

        with patch.object(
            adapter, "_http_post",
            side_effect=AdapterAuthError(adapter.name, "bad sid"),
        ):
            result = get_router().execute(
                Capability.SEND_SMS, dict(_VALID_SMS),
            )

        assert not result.ok
        stats = get_metrics().stats_for("twilio")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_failure"] == 1
        assert stats["calls_success"] == 0
