"""Tests for KlaviyoAdapter -- W963-103."""
from __future__ import annotations

from unittest.mock import patch

from core.adapters.base import Capability
from core.adapters.email.klaviyo import KlaviyoAdapter


# ── Configuration ─────────────────────────────────────────


class TestKlaviyoConfiguration:
    def test_is_configured_returns_false_without_key(self):
        with patch(
            "core.adapters.email._base.get_config"
        ) as mock_cfg:
            mock_cfg.return_value.get.return_value = ""
            adapter = KlaviyoAdapter()
            assert adapter.is_configured() is False

    def test_is_configured_returns_true_with_key(self):
        with patch(
            "core.adapters.email._base.get_config"
        ) as mock_cfg:
            mock_cfg.return_value.get.return_value = "pk_test_123"
            adapter = KlaviyoAdapter()
            assert adapter.is_configured() is True

    def test_config_alias_is_klaviyo(self):
        adapter = KlaviyoAdapter()
        assert adapter.config_alias == "klaviyo"


# ── Metadata ───────────────────────────────────────────────


class TestKlaviyoMetadata:
    def test_name(self):
        assert KlaviyoAdapter.name == "klaviyo"

    def test_capabilities_include_send_email(self):
        caps = KlaviyoAdapter.capabilities
        assert Capability.SEND_EMAIL_TRANSACTIONAL in caps
        assert Capability.SEND_EMAIL_CAMPAIGN in caps

    def test_priority_between_brevo_and_resend(self):
        """Brevo (90) wins free-tier volume; Klaviyo (80)
        wins e-commerce flow specialisation; Resend (75)
        is the developer-API fallback."""
        from core.adapters.email.brevo import BrevoAdapter
        from core.adapters.email.resend import ResendAdapter
        assert (
            ResendAdapter.priority
            < KlaviyoAdapter.priority
            < BrevoAdapter.priority
        )

    def test_base_url_is_klaviyo_api(self):
        adapter = KlaviyoAdapter()
        assert "klaviyo.com" in adapter.base_url


# ── Auth headers ───────────────────────────────────────────


class TestKlaviyoAuth:
    """Klaviyo uses a non-standard Authorization scheme:
    ``Authorization: Klaviyo-API-Key <KEY>`` not the
    default ``Bearer <KEY>``."""

    def test_auth_headers_use_klaviyo_scheme(self):
        with patch(
            "core.adapters.email._base.get_config"
        ) as mock_cfg:
            mock_cfg.return_value.get.return_value = "pk-abc123"
            adapter = KlaviyoAdapter()
            headers = adapter._auth_headers()
        assert "Authorization" in headers
        assert "Klaviyo-API-Key pk-abc123" == (
            headers["Authorization"]
        )
        # Klaviyo requires the revision header
        assert "revision" in headers

    def test_send_url_points_at_events_endpoint(self):
        adapter = KlaviyoAdapter()
        url = adapter._send_url()
        assert url.endswith("/events")


# ── Payload shape ──────────────────────────────────────────


class TestKlaviyoPayload:
    """Klaviyo events endpoint uses JSON:API style wrapper."""

    def test_payload_structure(self):
        adapter = KlaviyoAdapter()
        payload = adapter._build_payload({
            "to": "user@example.com",
            "from_email": "shop@example.com",
            "subject": "Hello",
            "html": "<p>Hi</p>",
            "text": "Hi",
            "tags": ["welcome"],
        })
        # JSON:API wrapper
        assert "data" in payload
        assert payload["data"]["type"] == "event"
        attrs = payload["data"]["attributes"]
        # Profile
        prof = attrs["profile"]["data"]
        assert prof["type"] == "profile"
        assert prof["attributes"]["email"] == "user@example.com"
        # Metric -- defaults to first tag
        metric = attrs["metric"]["data"]
        assert metric["type"] == "metric"
        assert metric["attributes"]["name"] == "welcome"
        # Properties carry the message body
        props = attrs["properties"]
        assert props["subject"] == "Hello"
        assert props["html_body"] == "<p>Hi</p>"
        assert props["text_body"] == "Hi"

    def test_payload_defaults_metric_when_no_tags(self):
        adapter = KlaviyoAdapter()
        payload = adapter._build_payload({
            "to": "u@x.com",
            "from_email": "s@x.com",
            "subject": "Hi",
            "html": "<p>x</p>",
        })
        metric = payload["data"]["attributes"]["metric"]["data"]
        assert metric["attributes"]["name"] == "transactional"


# ── Bootstrap registration ─────────────────────────────────


class TestKlaviyoBootstrap:
    def test_register_all_includes_klaviyo(self):
        from core.adapters.email.bootstrap import (
            _EMAIL_ADAPTER_CLASSES,
        )
        names = [cls.name for cls in _EMAIL_ADAPTER_CLASSES]
        assert "klaviyo" in names
        assert "brevo" in names
        assert "resend" in names
