"""Tests for the Phase 3 web search adapters + search_executor migration.

Real network calls are forbidden — every test patches the
adapter's HTTP layer to return canned responses.

Coverage:

  * SearchBaseAdapter — config gating, dedup, validation
  * DDGSAdapter — no-key default, HTML parser, redirect unwrap
  * BraveSearchAdapter — JSON parser, header auth
  * SerperAdapter — POST body, JSON parser
  * Bootstrap — register_all wires all 3 adapters
  * Router selection — DDGS picked when no keys, Brave wins
    when configured
  * search_executor.py migration — empty/dedup/router-dispatch
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


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Wipe every singleton + env var between tests."""
    for var in (
        "BRAVE_SEARCH_API_KEY", "SERPER_API_KEY",
        "PERPLEXITY_API_KEY", "TAVILY_API_KEY",
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


# ── SearchBaseAdapter ────────────────────────────────────────


class TestSearchBaseAdapter:
    def test_dedup_drops_duplicate_urls(self):
        from core.adapters.search._base import SearchBaseAdapter
        hits = [
            {"title": "A", "url": "https://x.com/1", "snippet": "",
             "source": "x.com", "retrieved_at": ""},
            {"title": "B", "url": "https://x.com/1", "snippet": "",
             "source": "x.com", "retrieved_at": ""},
            {"title": "C", "url": "https://y.com/2", "snippet": "",
             "source": "y.com", "retrieved_at": ""},
        ]
        out = SearchBaseAdapter._dedup_and_trim(hits, max_results=10)
        assert len(out) == 2
        assert out[0]["title"] == "A"  # first occurrence wins
        assert out[1]["title"] == "C"

    def test_dedup_case_insensitive(self):
        from core.adapters.search._base import SearchBaseAdapter
        hits = [
            {"title": "A", "url": "https://X.COM/1", "snippet": "",
             "source": "", "retrieved_at": ""},
            {"title": "B", "url": "https://x.com/1", "snippet": "",
             "source": "", "retrieved_at": ""},
        ]
        out = SearchBaseAdapter._dedup_and_trim(hits, max_results=10)
        assert len(out) == 1

    def test_dedup_trims_to_max_results(self):
        from core.adapters.search._base import SearchBaseAdapter
        hits = [
            {"title": f"{i}", "url": f"https://x.com/{i}", "snippet": "",
             "source": "", "retrieved_at": ""}
            for i in range(20)
        ]
        out = SearchBaseAdapter._dedup_and_trim(hits, max_results=5)
        assert len(out) == 5

    def test_dedup_skips_non_dict(self):
        from core.adapters.search._base import SearchBaseAdapter
        hits = [
            "not a dict",  # type: ignore[list-item]
            {"title": "A", "url": "https://x.com/1", "snippet": "",
             "source": "", "retrieved_at": ""},
        ]
        out = SearchBaseAdapter._dedup_and_trim(hits, max_results=10)  # type: ignore[arg-type]
        assert len(out) == 1


# ── DDGSAdapter ──────────────────────────────────────────────


class TestDDGSAdapter:
    def test_metadata(self):
        from core.adapters.search.ddgs import DDGSAdapter
        a = DDGSAdapter()
        assert a.name == "ddgs"
        assert a.category == AdapterCategory.SEARCH
        assert Capability.WEB_SEARCH in a.capabilities
        assert a.cost_per_call == 0.0
        assert a.config_alias == ""  # no API key

    def test_always_configured_no_key_needed(self):
        """DDGS never needs an API key — must be configured
        out of the box."""
        from core.adapters.search.ddgs import DDGSAdapter
        a = DDGSAdapter()
        assert a.is_configured() is True

    def test_unwrap_ddg_redirect(self):
        from core.adapters.search.ddgs import DDGSAdapter
        # Real DDG link format
        wrapped = (
            "//duckduckgo.com/l/?uddg="
            "https%3A%2F%2Fexample.com%2Fpage&rut=abc"
        )
        unwrapped = DDGSAdapter._unwrap_ddg_redirect(wrapped)
        assert unwrapped == "https://example.com/page"

    def test_unwrap_passes_through_normal_url(self):
        from core.adapters.search.ddgs import DDGSAdapter
        plain = "https://example.com/abc"
        assert DDGSAdapter._unwrap_ddg_redirect(plain) == plain

    def test_strip_tags_decodes_entities(self):
        from core.adapters.search.ddgs import DDGSAdapter
        text = "M&amp;Ms <b>are</b>   tasty"
        assert DDGSAdapter._strip_tags(text) == "M&Ms are tasty"

    def test_parse_html_extracts_results(self):
        from core.adapters.search.ddgs import DDGSAdapter
        html = """
        <div class="result__body">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage1">First result</a>
          <a class="result__snippet" href="...">First snippet text</a>
        </div>
        </div></div>
        <div class="result__body">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage2">Second result</a>
          <a class="result__snippet" href="...">Second snippet text</a>
        </div>
        </div></div>
        """
        a = DDGSAdapter()
        hits = a._parse_response(html, query="test")
        assert len(hits) == 2
        assert hits[0]["title"] == "First result"
        assert hits[0]["url"] == "https://example.com/page1"
        assert hits[0]["source"] == "example.com"
        assert hits[0]["snippet"] == "First snippet text"
        assert hits[1]["url"] == "https://example.com/page2"

    def test_execute_happy_path(self):
        from core.adapters.search.ddgs import DDGSAdapter
        a = DDGSAdapter()
        html = """
        <div class="result__body">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fshop.example.com%2Fproduct">Best Product 2026</a>
          <a class="result__snippet" href="...">Top-rated product review</a>
        </div>
        </div></div>
        """
        with patch.object(a, "_http_get", return_value=html):
            result = a.execute(
                Capability.WEB_SEARCH,
                {"query": "best product 2026"},
            )
        assert result.ok
        assert result.data["query"] == "best product 2026"
        assert result.data["count"] == 1
        assert result.data["hits"][0]["url"] == "https://shop.example.com/product"

    def test_execute_empty_query_validates(self):
        from core.adapters.search.ddgs import DDGSAdapter
        a = DDGSAdapter()
        result = a.execute(Capability.WEB_SEARCH, {"query": ""})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_execute_missing_query_validates(self):
        from core.adapters.search.ddgs import DDGSAdapter
        a = DDGSAdapter()
        result = a.execute(Capability.WEB_SEARCH, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── BraveSearchAdapter ───────────────────────────────────────


class TestBraveSearchAdapter:
    def test_metadata(self):
        from core.adapters.search.brave import BraveSearchAdapter
        a = BraveSearchAdapter()
        assert a.name == "brave_search"
        assert Capability.WEB_SEARCH in a.capabilities
        assert a.priority == 90  # higher than DDGS
        assert a.free_tier_monthly_limit == 2_000

    def test_unconfigured_without_key(self):
        from core.adapters.search.brave import BraveSearchAdapter
        a = BraveSearchAdapter()
        assert not a.is_configured()

    def test_configured_when_env_set(self, monkeypatch):
        from core.adapters.search.brave import BraveSearchAdapter
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "BSA_test")
        get_config().reload()
        a = BraveSearchAdapter()
        assert a.is_configured()

    def test_execute_happy_path(self, monkeypatch):
        from core.adapters.search.brave import BraveSearchAdapter
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "BSA_test")
        get_config().reload()

        a = BraveSearchAdapter()
        with patch.object(a, "_http_get", return_value={
            "web": {
                "results": [
                    {
                        "title": "Brave result 1",
                        "url": "https://example.com/1",
                        "description": "First description",
                        "profile": {"name": "example.com"},
                    },
                    {
                        "title": "Brave result 2",
                        "url": "https://example.com/2",
                        "description": "Second description",
                    },
                ],
            },
        }) as mocked:
            result = a.execute(
                Capability.WEB_SEARCH,
                {"query": "competitor research", "max_results": 10},
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["hits"][0]["title"] == "Brave result 1"
        assert result.data["hits"][0]["snippet"] == "First description"
        # API key in header
        called_headers = mocked.call_args.kwargs["headers"]
        assert called_headers["X-Subscription-Token"] == "BSA_test"

    def test_execute_handles_empty_results(self, monkeypatch):
        from core.adapters.search.brave import BraveSearchAdapter
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
        get_config().reload()
        a = BraveSearchAdapter()
        with patch.object(a, "_http_get", return_value={"web": {"results": []}}):
            result = a.execute(Capability.WEB_SEARCH, {"query": "x"})
        assert result.ok
        assert result.data["count"] == 0

    def test_execute_handles_malformed_response(self, monkeypatch):
        from core.adapters.search.brave import BraveSearchAdapter
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
        get_config().reload()
        a = BraveSearchAdapter()
        # Brave returns a string instead of dict (e.g., HTML error page)
        with patch.object(a, "_http_get", return_value="<html>error</html>"):
            result = a.execute(Capability.WEB_SEARCH, {"query": "x"})
        # Empty hits, but request succeeded → ok
        assert result.ok
        assert result.data["count"] == 0


# ── SerperAdapter ────────────────────────────────────────────


class TestSerperAdapter:
    def test_metadata(self):
        from core.adapters.search.serper import SerperAdapter
        a = SerperAdapter()
        assert a.name == "serper"
        assert Capability.WEB_SEARCH in a.capabilities
        assert a.priority == 80  # below Brave (90), above DDGS (50)
        assert a.free_tier_monthly_limit == 2_500

    def test_unconfigured_without_key(self):
        from core.adapters.search.serper import SerperAdapter
        a = SerperAdapter()
        assert not a.is_configured()

    def test_execute_uses_post_with_json_body(self, monkeypatch):
        from core.adapters.search.serper import SerperAdapter
        monkeypatch.setenv("SERPER_API_KEY", "ser_test")
        get_config().reload()

        a = SerperAdapter()
        captured = {}

        def fake_post(url, body, headers):
            captured["url"] = url
            captured["body"] = body
            captured["headers"] = headers
            return {
                "organic": [
                    {
                        "title": "Top result",
                        "link": "https://example.com/top",
                        "snippet": "First snippet",
                    },
                    {
                        "title": "Second",
                        "link": "https://example.com/two",
                        "snippet": "Second snippet",
                    },
                ],
            }

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.WEB_SEARCH,
                {"query": "test query", "max_results": 5},
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["hits"][0]["url"] == "https://example.com/top"
        # Verify the POST body shape
        assert captured["body"]["q"] == "test query"
        assert captured["body"]["num"] == 5
        # Verify the auth header
        assert captured["headers"]["X-API-KEY"] == "ser_test"


# ── Bootstrap + Router selection ────────────────────────────


class TestSearchBootstrap:
    def test_register_all_adds_five_adapters(self):
        from core.adapters.search.bootstrap import register_all
        status = register_all()
        assert len(status) == 5
        assert set(status.keys()) == {
            "brave_search", "perplexity", "serper", "tavily", "ddgs",
        }

    def test_ddgs_always_configured(self):
        """DDGS has no API key requirement so it's always
        configured — exactly the role Ollama plays for LLMs."""
        from core.adapters.search.bootstrap import register_all
        status = register_all()
        assert status["ddgs"] is True
        assert status["brave_search"] is False
        assert status["serper"] is False
        assert status["perplexity"] is False
        assert status["tavily"] is False

    def test_register_all_idempotent(self):
        from core.adapters.search.bootstrap import register_all
        register_all()
        register_all()  # second call must not raise
        assert len(get_registry()) == 5

    def test_router_picks_ddgs_when_only_ddgs_configured(self):
        from core.adapters.search.bootstrap import register_all
        register_all()
        chosen = get_router().route(Capability.WEB_SEARCH)
        assert chosen.name == "ddgs"

    def test_router_picks_brave_when_configured(self, monkeypatch):
        """When Brave's API key is set the router prefers it
        over DDGS — Brave is priority 90, DDGS is 50."""
        from core.adapters.search.bootstrap import register_all
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
        get_config().reload()
        register_all()
        chosen = get_router().route(Capability.WEB_SEARCH)
        assert chosen.name == "brave_search"

    def test_router_picks_brave_over_serper(self, monkeypatch):
        from core.adapters.search.bootstrap import register_all
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
        monkeypatch.setenv("SERPER_API_KEY", "k")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        get_config().reload()
        register_all()
        chain = get_router().candidates(Capability.WEB_SEARCH)
        names = [a.name for a in chain]
        # Brave first (90), Perplexity + Serper (80), Tavily (75), DDGS (50)
        assert names[0] == "brave_search"
        assert names[-1] == "ddgs"
        assert "perplexity" in names
        assert "tavily" in names


# ── search_executor.py migration ─────────────────────────────


class TestSearchExecutorMigration:
    def test_empty_queries_returns_empty(self):
        from engines.auto_research.search_executor import execute_searches
        assert execute_searches([]) == []

    def test_no_router_returns_empty(self):
        """When no search adapter is registered the function
        still returns ``[]`` — cleanup invariant preserved."""
        from engines.auto_research.search_executor import execute_searches
        # Registry was reset by the autouse fixture, so no
        # search adapters are registered.
        result = execute_searches([
            {"text": "pricing strategy", "angle": "s", "priority": 1.0},
        ])
        assert result == []

    def test_router_dispatches_to_adapter(self):
        """When a search adapter IS registered, the function
        actually returns its results."""
        from engines.auto_research.search_executor import execute_searches

        class _FakeSearchAdapter(BaseAdapter):
            name = "fake_search"
            category = AdapterCategory.SEARCH
            capabilities = {Capability.WEB_SEARCH}
            priority = 100
            def is_configured(self): return True
            def _execute(self, c, p):
                return AdapterResult.success(
                    adapter=self.name,
                    capability=c.value,
                    data={
                        "query": p["query"],
                        "hits": [
                            {
                                "title": f"Result for {p['query']}",
                                "url": f"https://example.com/{p['query']}",
                                "snippet": "stub snippet",
                                "source": "example.com",
                                "retrieved_at": "2026-04-08T00:00:00Z",
                            },
                        ],
                        "count": 1,
                    },
                )
        get_registry().register(_FakeSearchAdapter())

        result = execute_searches([
            {"text": "alpha", "angle": "s", "priority": 1.0},
            {"text": "beta", "angle": "s", "priority": 1.0},
        ])
        assert len(result) == 2
        assert result[0]["title"] == "Result for alpha"
        assert result[1]["title"] == "Result for beta"
        # Field shape matches RawSearchResult
        for r in result:
            assert "title" in r
            assert "url" in r
            assert "snippet" in r
            assert "source" in r
            assert "retrieved_at" in r

    def test_router_dedup_across_queries(self):
        """If two queries return the same URL, the dedup layer
        in execute_searches drops the duplicate."""
        from engines.auto_research.search_executor import execute_searches

        class _DupAdapter(BaseAdapter):
            name = "dup_search"
            category = AdapterCategory.SEARCH
            capabilities = {Capability.WEB_SEARCH}
            priority = 100
            def is_configured(self): return True
            def _execute(self, c, p):
                return AdapterResult.success(
                    adapter=self.name,
                    capability=c.value,
                    data={
                        "query": p["query"],
                        "hits": [{
                            "title": "Same article",
                            "url": "https://example.com/duplicate",
                            "snippet": "...",
                            "source": "example.com",
                            "retrieved_at": "2026-04-08T00:00:00Z",
                        }],
                        "count": 1,
                    },
                )
        get_registry().register(_DupAdapter())

        result = execute_searches([
            {"text": "alpha", "angle": "s", "priority": 1.0},
            {"text": "beta", "angle": "s", "priority": 1.0},
        ])
        # Only one URL → only one result after dedup
        assert len(result) == 1

    def test_router_failure_swallowed(self):
        """If the only configured search adapter raises, the
        function returns ``[]`` instead of propagating."""
        from engines.auto_research.search_executor import execute_searches

        class _Broken(BaseAdapter):
            name = "broken_search"
            category = AdapterCategory.SEARCH
            capabilities = {Capability.WEB_SEARCH}
            def is_configured(self): return True
            def _execute(self, c, p):
                raise AdapterUnavailable(self.name, "down")
        get_registry().register(_Broken())

        result = execute_searches([
            {"text": "alpha", "angle": "s", "priority": 1.0},
        ])
        assert result == []

    def test_caller_query_list_not_mutated(self):
        """The function works on a deep copy — the caller's
        query list must NOT change after the call."""
        from engines.auto_research.search_executor import execute_searches
        original = [
            {"text": "alpha", "angle": "s", "priority": 1.0},
        ]
        execute_searches(original)
        assert original[0]["text"] == "alpha"

    def test_simulated_corpus_constant_still_gone(self):
        """Pin: the cleanup must NOT regress."""
        import engines.auto_research.search_executor as se
        assert not hasattr(se, "_SIMULATED_CORPUS")
        assert not hasattr(se, "_simulate_search")
