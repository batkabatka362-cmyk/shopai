"""Tests for the SimilarWeb competitor intelligence adapter."""
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
    monkeypatch.delenv("SIMILARWEB_API_KEY", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_similarweb(monkeypatch, *, key="sw-test-key"):
    monkeypatch.setenv("SIMILARWEB_API_KEY", key)
    get_config().reload()


class TestSimilarWebMetadata:
    def test_metadata(self):
        from core.adapters.search.similarweb import SimilarWebAdapter
        a = SimilarWebAdapter()
        assert a.name == "similarweb"
        assert a.category == AdapterCategory.SEARCH
        assert Capability.WEB_SEARCH in a.capabilities
        assert a.priority == 65

    def test_unconfigured_without_key(self):
        from core.adapters.search.similarweb import SimilarWebAdapter
        assert not SimilarWebAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.search.similarweb import SimilarWebAdapter
        _configure_similarweb(monkeypatch)
        assert SimilarWebAdapter().is_configured()


class TestSimilarWebSearch:
    def test_domain_traffic_happy_path(self, monkeypatch):
        from core.adapters.search.similarweb import SimilarWebAdapter
        _configure_similarweb(monkeypatch)
        a = SimilarWebAdapter()

        raw = {
            "visits": [
                {"date": "2026-01-01", "visits": 1500000},
                {"date": "2026-02-01", "visits": 1800000},
                {"date": "2026-03-01", "visits": 2000000},
            ],
        }

        with patch.object(a, "_http_get", return_value=raw):
            result = a.execute(
                Capability.WEB_SEARCH,
                {"domain": "shopify.com"},
            )

        assert result.ok
        assert result.data["domain"] == "shopify.com"
        assert result.data["total_visits"] == 5300000
        assert len(result.data["visits"]) == 3
        assert result.data["count"] == 1

    def test_strips_protocol(self, monkeypatch):
        from core.adapters.search.similarweb import SimilarWebAdapter
        _configure_similarweb(monkeypatch)
        a = SimilarWebAdapter()

        raw = {"visits": []}

        with patch.object(a, "_http_get", return_value=raw):
            result = a.execute(
                Capability.WEB_SEARCH,
                {"domain": "https://shopify.com/pricing"},
            )

        assert result.ok
        assert result.data["domain"] == "shopify.com"

    def test_empty_query_rejected(self, monkeypatch):
        from core.adapters.search.similarweb import SimilarWebAdapter
        _configure_similarweb(monkeypatch)
        a = SimilarWebAdapter()

        result = a.execute(Capability.WEB_SEARCH, {})
        assert not result.ok


class TestSimilarWebBootstrap:
    def test_register_all_includes_similarweb(self):
        from core.adapters.search.bootstrap import register_all
        status = register_all()
        assert "similarweb" in status
