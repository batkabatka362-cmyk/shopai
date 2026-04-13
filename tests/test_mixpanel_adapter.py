"""Tests for the Mixpanel analytics adapter."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterValidationError,
    Capability,
    get_config,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("MIXPANEL_TOKEN", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_mixpanel(monkeypatch, *, key="mp-test-token"):
    monkeypatch.setenv("MIXPANEL_TOKEN", key)
    get_config().reload()


class TestMixpanelMetadata:
    def test_metadata(self):
        from core.adapters.analytics.mixpanel import MixpanelAdapter
        a = MixpanelAdapter()
        assert a.name == "mixpanel"
        assert a.category == AdapterCategory.ANALYTICS
        assert Capability.ANALYTICS_TRACK_EVENT in a.capabilities
        assert Capability.ANALYTICS_IDENTIFY in a.capabilities
        assert Capability.ANALYTICS_QUERY in a.capabilities
        assert a.priority == 80

    def test_unconfigured_without_key(self):
        from core.adapters.analytics.mixpanel import MixpanelAdapter
        assert not MixpanelAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.analytics.mixpanel import MixpanelAdapter
        _configure_mixpanel(monkeypatch)
        assert MixpanelAdapter().is_configured()


class TestMixpanelTrack:
    def test_track_event_happy_path(self, monkeypatch):
        from core.adapters.analytics.mixpanel import MixpanelAdapter
        _configure_mixpanel(monkeypatch)
        a = MixpanelAdapter()

        raw = {"status": 1}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            result = a.execute(
                Capability.ANALYTICS_TRACK_EVENT,
                {
                    "event": "purchase",
                    "distinct_id": "user_456",
                    "properties": {"amount": 49.99},
                },
            )

        assert result.ok
        assert result.data["event"] == "purchase"
        assert result.data["tracked"] is True

        body = mocked.call_args[0][1]
        assert body[0]["event"] == "purchase"
        assert body[0]["properties"]["token"] == "mp-test-token"
        assert body[0]["properties"]["distinct_id"] == "user_456"

    def test_track_requires_event(self, monkeypatch):
        from core.adapters.analytics.mixpanel import MixpanelAdapter
        _configure_mixpanel(monkeypatch)
        a = MixpanelAdapter()

        result = a.execute(
            Capability.ANALYTICS_TRACK_EVENT,
            {"distinct_id": "user_456"},
        )
        assert not result.ok


class TestMixpanelIdentify:
    def test_identify_happy_path(self, monkeypatch):
        from core.adapters.analytics.mixpanel import MixpanelAdapter
        _configure_mixpanel(monkeypatch)
        a = MixpanelAdapter()

        raw = {"status": 1}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            result = a.execute(
                Capability.ANALYTICS_IDENTIFY,
                {
                    "distinct_id": "user_456",
                    "properties": {"name": "Jane", "email": "jane@example.com"},
                },
            )

        assert result.ok
        assert result.data["identified"] is True

        body = mocked.call_args[0][1]
        assert body[0]["$distinct_id"] == "user_456"
        assert body[0]["$set"]["name"] == "Jane"

    def test_identify_requires_distinct_id(self, monkeypatch):
        from core.adapters.analytics.mixpanel import MixpanelAdapter
        _configure_mixpanel(monkeypatch)
        a = MixpanelAdapter()

        result = a.execute(Capability.ANALYTICS_IDENTIFY, {})
        assert not result.ok


class TestMixpanelQuery:
    def test_query_happy_path(self, monkeypatch):
        from core.adapters.analytics.mixpanel import MixpanelAdapter
        _configure_mixpanel(monkeypatch)
        a = MixpanelAdapter()

        raw = {"results": [{"event": "purchase", "count": 42}]}

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(
                Capability.ANALYTICS_QUERY,
                {"event": "purchase", "from_date": "2026-04-01", "to_date": "2026-04-13"},
            )

        assert result.ok
        assert result.data["count"] == 1
        assert result.data["event"] == "purchase"

    def test_query_requires_event(self, monkeypatch):
        from core.adapters.analytics.mixpanel import MixpanelAdapter
        _configure_mixpanel(monkeypatch)
        a = MixpanelAdapter()

        result = a.execute(Capability.ANALYTICS_QUERY, {})
        assert not result.ok


class TestMixpanelBootstrap:
    def test_register_all_includes_mixpanel(self):
        from core.adapters.analytics.bootstrap import register_all
        status = register_all()
        assert "mixpanel" in status
