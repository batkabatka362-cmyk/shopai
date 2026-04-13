"""Tests for the Perplexity AI search adapter.

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
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_perplexity(monkeypatch, *, key="pplx-test-key"):
    monkeypatch.setenv("PERPLEXITY_API_KEY", key)
    get_config().reload()


class TestPerplexityMetadata:
    def test_metadata(self):
        from core.adapters.search.perplexity import PerplexityAdapter
        a = PerplexityAdapter()
        assert a.name == "perplexity"
        assert a.category == AdapterCategory.SEARCH
        assert Capability.WEB_SEARCH in a.capabilities
        assert Capability.DEEP_RESEARCH in a.capabilities
        assert a.priority == 80

    def test_unconfigured_without_key(self):
        from core.adapters.search.perplexity import PerplexityAdapter
        assert not PerplexityAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.search.perplexity import PerplexityAdapter
        _configure_perplexity(monkeypatch)
        assert PerplexityAdapter().is_configured()


class TestPerplexityValidation:
    def test_empty_query_rejected(self, monkeypatch):
        from core.adapters.search.perplexity import PerplexityAdapter
        _configure_perplexity(monkeypatch)
        a = PerplexityAdapter()

        result = a.execute(Capability.WEB_SEARCH, {"query": ""})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_missing_query_rejected(self, monkeypatch):
        from core.adapters.search.perplexity import PerplexityAdapter
        _configure_perplexity(monkeypatch)
        a = PerplexityAdapter()

        result = a.execute(Capability.WEB_SEARCH, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


class TestPerplexitySearch:
    def test_web_search_happy_path(self, monkeypatch):
        from core.adapters.search.perplexity import PerplexityAdapter
        _configure_perplexity(monkeypatch)
        a = PerplexityAdapter()

        raw = {
            "choices": [{
                "message": {
                    "content": "Shopify is an e-commerce platform...",
                },
            }],
            "citations": [
                "https://shopify.com/about",
                "https://en.wikipedia.org/wiki/Shopify",
            ],
        }

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            result = a.execute(
                Capability.WEB_SEARCH,
                {"query": "What is Shopify?"},
            )

        assert result.ok
        assert result.data["query"] == "What is Shopify?"
        assert result.data["answer"] == "Shopify is an e-commerce platform..."
        assert result.data["count"] == 2
        assert result.data["model"] == "sonar"
        assert result.data["hits"][0]["url"] == "https://shopify.com/about"

        # Verify the POST body
        call_args = mocked.call_args
        body = call_args[0][1]
        assert body["model"] == "sonar"
        assert body["messages"][0]["content"] == "What is Shopify?"

    def test_deep_research_uses_correct_model(self, monkeypatch):
        from core.adapters.search.perplexity import PerplexityAdapter
        _configure_perplexity(monkeypatch)
        a = PerplexityAdapter()

        raw = {
            "choices": [{"message": {"content": "Deep analysis..."}}],
            "citations": [],
        }

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            result = a.execute(
                Capability.DEEP_RESEARCH,
                {"query": "E-commerce market trends 2026"},
            )

        assert result.ok
        assert result.data["model"] == "sonar-deep-research"
        body = mocked.call_args[0][1]
        assert body["model"] == "sonar-deep-research"

    def test_system_prompt_injected(self, monkeypatch):
        from core.adapters.search.perplexity import PerplexityAdapter
        _configure_perplexity(monkeypatch)
        a = PerplexityAdapter()

        raw = {"choices": [{"message": {"content": "..."}}], "citations": []}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            a.execute(
                Capability.WEB_SEARCH,
                {"query": "test", "system": "You are a market analyst."},
            )

        body = mocked.call_args[0][1]
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][0]["content"] == "You are a market analyst."
        assert body["messages"][1]["role"] == "user"

    def test_dict_citations_parsed(self, monkeypatch):
        from core.adapters.search.perplexity import PerplexityAdapter
        _configure_perplexity(monkeypatch)
        a = PerplexityAdapter()

        raw = {
            "choices": [{"message": {"content": "Answer"}}],
            "citations": [
                {"title": "Shopify Docs", "url": "https://shopify.dev", "snippet": "API reference"},
            ],
        }

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(Capability.WEB_SEARCH, {"query": "Shopify API"})

        assert result.ok
        assert result.data["hits"][0]["title"] == "Shopify Docs"
        assert result.data["hits"][0]["snippet"] == "API reference"

    def test_empty_response_handled(self, monkeypatch):
        from core.adapters.search.perplexity import PerplexityAdapter
        _configure_perplexity(monkeypatch)
        a = PerplexityAdapter()

        raw = {"choices": [], "citations": []}

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(Capability.WEB_SEARCH, {"query": "test"})

        assert result.ok
        assert result.data["answer"] == ""
        assert result.data["count"] == 0

    def test_custom_model_override(self, monkeypatch):
        from core.adapters.search.perplexity import PerplexityAdapter
        _configure_perplexity(monkeypatch)
        a = PerplexityAdapter()

        raw = {"choices": [{"message": {"content": "..."}}], "citations": []}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            a.execute(
                Capability.WEB_SEARCH,
                {"query": "test", "model": "sonar-pro"},
            )

        body = mocked.call_args[0][1]
        assert body["model"] == "sonar-pro"


class TestPerplexityBootstrap:
    def test_register_all_includes_perplexity(self):
        from core.adapters.search.bootstrap import register_all
        status = register_all()
        assert "perplexity" in status

    def test_router_finds_perplexity(self, monkeypatch):
        from core.adapters.search.bootstrap import register_all
        _configure_perplexity(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.DEEP_RESEARCH)
        assert chosen.name == "perplexity"
