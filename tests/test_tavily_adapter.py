"""Tests for the Tavily AI search adapter.

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
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_tavily(monkeypatch, *, key="tvly-test-key"):
    monkeypatch.setenv("TAVILY_API_KEY", key)
    get_config().reload()


class TestTavilyMetadata:
    def test_metadata(self):
        from core.adapters.search.tavily import TavilyAdapter
        a = TavilyAdapter()
        assert a.name == "tavily"
        assert a.category == AdapterCategory.SEARCH
        assert Capability.WEB_SEARCH in a.capabilities
        assert Capability.DEEP_RESEARCH in a.capabilities
        assert a.priority == 75
        assert a.free_tier_monthly_limit == 1000

    def test_unconfigured_without_key(self):
        from core.adapters.search.tavily import TavilyAdapter
        assert not TavilyAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.search.tavily import TavilyAdapter
        _configure_tavily(monkeypatch)
        assert TavilyAdapter().is_configured()


class TestTavilyValidation:
    def test_empty_query_rejected(self, monkeypatch):
        from core.adapters.search.tavily import TavilyAdapter
        _configure_tavily(monkeypatch)
        a = TavilyAdapter()

        result = a.execute(Capability.WEB_SEARCH, {"query": ""})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_missing_query_rejected(self, monkeypatch):
        from core.adapters.search.tavily import TavilyAdapter
        _configure_tavily(monkeypatch)
        a = TavilyAdapter()

        result = a.execute(Capability.WEB_SEARCH, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


class TestTavilySearch:
    def test_web_search_happy_path(self, monkeypatch):
        from core.adapters.search.tavily import TavilyAdapter
        _configure_tavily(monkeypatch)
        a = TavilyAdapter()

        raw = {
            "answer": "Shopify is used by millions of merchants...",
            "results": [
                {
                    "title": "Shopify Official",
                    "url": "https://shopify.com",
                    "content": "E-commerce platform for online stores",
                },
                {
                    "title": "Shopify Review 2026",
                    "url": "https://example.com/review",
                    "content": "Detailed review of Shopify features",
                },
            ],
        }

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            result = a.execute(
                Capability.WEB_SEARCH,
                {"query": "Shopify review"},
            )

        assert result.ok
        assert result.data["query"] == "Shopify review"
        assert result.data["answer"] == "Shopify is used by millions of merchants..."
        assert result.data["count"] == 2
        assert result.data["search_depth"] == "basic"
        assert result.data["hits"][0]["title"] == "Shopify Official"
        assert result.data["hits"][0]["snippet"] == "E-commerce platform for online stores"

        # Verify POST body includes API key
        body = mocked.call_args[0][1]
        assert body["api_key"] == "tvly-test-key"
        assert body["query"] == "Shopify review"
        assert body["search_depth"] == "basic"

    def test_deep_research_uses_advanced_depth(self, monkeypatch):
        from core.adapters.search.tavily import TavilyAdapter
        _configure_tavily(monkeypatch)
        a = TavilyAdapter()

        raw = {"answer": "In-depth analysis...", "results": []}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            result = a.execute(
                Capability.DEEP_RESEARCH,
                {"query": "E-commerce market analysis 2026"},
            )

        assert result.ok
        assert result.data["search_depth"] == "advanced"
        body = mocked.call_args[0][1]
        assert body["search_depth"] == "advanced"

    def test_include_domains_passed(self, monkeypatch):
        from core.adapters.search.tavily import TavilyAdapter
        _configure_tavily(monkeypatch)
        a = TavilyAdapter()

        raw = {"answer": "", "results": []}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            a.execute(
                Capability.WEB_SEARCH,
                {
                    "query": "test",
                    "include_domains": ["shopify.com", "shopify.dev"],
                },
            )

        body = mocked.call_args[0][1]
        assert body["include_domains"] == ["shopify.com", "shopify.dev"]

    def test_exclude_domains_passed(self, monkeypatch):
        from core.adapters.search.tavily import TavilyAdapter
        _configure_tavily(monkeypatch)
        a = TavilyAdapter()

        raw = {"answer": "", "results": []}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            a.execute(
                Capability.WEB_SEARCH,
                {
                    "query": "test",
                    "exclude_domains": ["reddit.com"],
                },
            )

        body = mocked.call_args[0][1]
        assert body["exclude_domains"] == ["reddit.com"]

    def test_topic_filter_passed(self, monkeypatch):
        from core.adapters.search.tavily import TavilyAdapter
        _configure_tavily(monkeypatch)
        a = TavilyAdapter()

        raw = {"answer": "", "results": []}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            a.execute(
                Capability.WEB_SEARCH,
                {"query": "test", "topic": "news"},
            )

        body = mocked.call_args[0][1]
        assert body["topic"] == "news"

    def test_empty_results_handled(self, monkeypatch):
        from core.adapters.search.tavily import TavilyAdapter
        _configure_tavily(monkeypatch)
        a = TavilyAdapter()

        raw = {"answer": "", "results": []}

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(Capability.WEB_SEARCH, {"query": "obscure topic"})

        assert result.ok
        assert result.data["count"] == 0
        assert result.data["hits"] == []

    def test_max_results_forwarded(self, monkeypatch):
        from core.adapters.search.tavily import TavilyAdapter
        _configure_tavily(monkeypatch)
        a = TavilyAdapter()

        raw = {"answer": "", "results": []}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            a.execute(
                Capability.WEB_SEARCH,
                {"query": "test", "max_results": 5},
            )

        body = mocked.call_args[0][1]
        assert body["max_results"] == 5


class TestTavilyBootstrap:
    def test_register_all_includes_tavily(self):
        from core.adapters.search.bootstrap import register_all
        status = register_all()
        assert "tavily" in status

    def test_router_finds_tavily_for_deep_research(self, monkeypatch):
        from core.adapters.search.bootstrap import register_all
        _configure_tavily(monkeypatch)
        register_all()
        # Tavily should be available for DEEP_RESEARCH
        candidates = get_router().candidates(Capability.DEEP_RESEARCH)
        names = [a.name for a in candidates]
        assert "tavily" in names
