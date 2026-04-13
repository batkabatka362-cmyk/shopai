"""Tests for the PostHog analytics adapter."""
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
    monkeypatch.delenv("POSTHOG_API_KEY", raising=False)
    monkeypatch.delenv("POSTHOG_HOST", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_posthog(monkeypatch, *, key="phc_test123"):
    monkeypatch.setenv("POSTHOG_API_KEY", key)
    get_config().reload()


class TestPostHogMetadata:
    def test_metadata(self):
        from core.adapters.analytics.posthog import PostHogAdapter
        a = PostHogAdapter()
        assert a.name == "posthog"
        assert a.category == AdapterCategory.ANALYTICS
        assert Capability.ANALYTICS_TRACK_EVENT in a.capabilities
        assert Capability.ANALYTICS_IDENTIFY in a.capabilities
        assert Capability.ANALYTICS_QUERY in a.capabilities
        assert a.priority == 85

    def test_unconfigured_without_key(self):
        from core.adapters.analytics.posthog import PostHogAdapter
        assert not PostHogAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.analytics.posthog import PostHogAdapter
        _configure_posthog(monkeypatch)
        assert PostHogAdapter().is_configured()


class TestPostHogTrack:
    def test_track_event_happy_path(self, monkeypatch):
        from core.adapters.analytics.posthog import PostHogAdapter
        _configure_posthog(monkeypatch)
        a = PostHogAdapter()

        raw = {"status": 1}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            result = a.execute(
                Capability.ANALYTICS_TRACK_EVENT,
                {
                    "event": "order_placed",
                    "distinct_id": "user_123",
                    "properties": {"order_total": 99.99},
                },
            )

        assert result.ok
        assert result.data["event"] == "order_placed"
        assert result.data["distinct_id"] == "user_123"
        assert result.data["captured"] is True

        body = mocked.call_args[0][1]
        assert body["api_key"] == "phc_test123"
        assert body["event"] == "order_placed"

    def test_track_requires_event(self, monkeypatch):
        from core.adapters.analytics.posthog import PostHogAdapter
        _configure_posthog(monkeypatch)
        a = PostHogAdapter()

        result = a.execute(
            Capability.ANALYTICS_TRACK_EVENT,
            {"distinct_id": "user_123"},
        )
        assert not result.ok

    def test_track_requires_distinct_id(self, monkeypatch):
        from core.adapters.analytics.posthog import PostHogAdapter
        _configure_posthog(monkeypatch)
        a = PostHogAdapter()

        result = a.execute(
            Capability.ANALYTICS_TRACK_EVENT,
            {"event": "test"},
        )
        assert not result.ok


class TestPostHogIdentify:
    def test_identify_happy_path(self, monkeypatch):
        from core.adapters.analytics.posthog import PostHogAdapter
        _configure_posthog(monkeypatch)
        a = PostHogAdapter()

        raw = {"status": 1}

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(
                Capability.ANALYTICS_IDENTIFY,
                {
                    "distinct_id": "user_123",
                    "properties": {"name": "John", "plan": "premium"},
                },
            )

        assert result.ok
        assert result.data["identified"] is True


class TestPostHogQuery:
    def test_query_happy_path(self, monkeypatch):
        from core.adapters.analytics.posthog import PostHogAdapter
        _configure_posthog(monkeypatch)
        a = PostHogAdapter()

        raw = {
            "results": [["2026-04-01", 150], ["2026-04-02", 200]],
            "columns": ["date", "count"],
        }

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(
                Capability.ANALYTICS_QUERY,
                {"query": "SELECT count() FROM events WHERE event = 'order_placed'"},
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["columns"] == ["date", "count"]

    def test_query_requires_query(self, monkeypatch):
        from core.adapters.analytics.posthog import PostHogAdapter
        _configure_posthog(monkeypatch)
        a = PostHogAdapter()

        result = a.execute(Capability.ANALYTICS_QUERY, {})
        assert not result.ok


class TestPostHogBootstrap:
    def test_register_all_includes_posthog(self):
        from core.adapters.analytics.bootstrap import register_all
        status = register_all()
        assert "posthog" in status

    def test_router_finds_posthog(self, monkeypatch):
        from core.adapters.analytics.bootstrap import register_all
        _configure_posthog(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.ANALYTICS_TRACK_EVENT)
        assert chosen.name == "posthog"
