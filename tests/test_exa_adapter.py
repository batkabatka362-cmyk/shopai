"""Tests for the Exa neural search adapter."""
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
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_exa(monkeypatch, *, key="exa-test-key"):
    monkeypatch.setenv("EXA_API_KEY", key)
    get_config().reload()


class TestExaMetadata:
    def test_metadata(self):
        from core.adapters.search.exa import ExaAdapter
        a = ExaAdapter()
        assert a.name == "exa"
        assert a.category == AdapterCategory.SEARCH
        assert Capability.WEB_SEARCH in a.capabilities
        assert a.priority == 70

    def test_unconfigured_without_key(self):
        from core.adapters.search.exa import ExaAdapter
        assert not ExaAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.search.exa import ExaAdapter
        _configure_exa(monkeypatch)
        assert ExaAdapter().is_configured()


class TestExaSearch:
    def test_search_happy_path(self, monkeypatch):
        from core.adapters.search.exa import ExaAdapter
        _configure_exa(monkeypatch)
        a = ExaAdapter()

        raw = {
            "results": [
                {"title": "Best Running Shoes 2026", "url": "https://example.com/shoes", "text": "Review of top shoes"},
                {"title": "Athletic Wear Guide", "url": "https://example.com/guide", "text": "Complete guide"},
            ],
        }

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            result = a.execute(
                Capability.WEB_SEARCH,
                {"query": "best running shoes", "type": "neural"},
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["search_type"] == "neural"
        assert result.data["hits"][0]["title"] == "Best Running Shoes 2026"

        body = mocked.call_args[0][1]
        assert body["type"] == "neural"
        headers = mocked.call_args[0][2]
        assert headers["x-api-key"] == "exa-test-key"

    def test_empty_query_rejected(self, monkeypatch):
        from core.adapters.search.exa import ExaAdapter
        _configure_exa(monkeypatch)
        a = ExaAdapter()

        result = a.execute(Capability.WEB_SEARCH, {"query": ""})
        assert not result.ok

    def test_include_domains_forwarded(self, monkeypatch):
        from core.adapters.search.exa import ExaAdapter
        _configure_exa(monkeypatch)
        a = ExaAdapter()

        raw = {"results": []}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            a.execute(
                Capability.WEB_SEARCH,
                {"query": "test", "include_domains": ["shopify.com"]},
            )

        body = mocked.call_args[0][1]
        assert body["includeDomains"] == ["shopify.com"]


class TestExaBootstrap:
    def test_register_all_includes_exa(self):
        from core.adapters.search.bootstrap import register_all
        status = register_all()
        assert "exa" in status
