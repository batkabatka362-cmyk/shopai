"""SearchAgent regression — cross-source search orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from agents.search import SearchAgent, SearchResult


@dataclass
class _FakeResult:
    ok: bool = True
    adapter: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: Any = None


def _router_with(calls: dict[str, _FakeResult]):
    """Build a mock router that returns pre-canned results
    per capability value."""
    router = MagicMock()

    def execute(capability, params):
        key = capability.value
        if key in calls:
            return calls[key]
        return _FakeResult(ok=False, error=RuntimeError("no adapter"))

    router.execute.side_effect = execute
    return router


# ── Scope handling ──────────────────────────────────────────


class TestScope:
    def test_empty_query_raises(self):
        agent = SearchAgent(router=None)
        with pytest.raises(ValueError):
            agent.search("")
        with pytest.raises(ValueError):
            agent.search("   ")

    def test_bad_scope_raises(self):
        agent = SearchAgent(router=None)
        with pytest.raises(ValueError):
            agent.search("cozy lamp", scope=("blogs",))

    def test_bad_limit_raises(self):
        agent = SearchAgent(router=None)
        with pytest.raises(ValueError):
            agent.search("x", limit="nope")

    def test_no_router_returns_empty(self):
        agent = SearchAgent(router=None)
        assert agent.search("cozy lamp") == []

    def test_all_scope_expands_to_both(self):
        calls = {
            "web_search": _FakeResult(
                ok=True, adapter="serper",
                data={"results": [
                    {"title": "t1", "url": "https://x/1"},
                ]},
            ),
            "sourcing_search_products": _FakeResult(
                ok=True, adapter="cj_dropshipping",
                data={"products": [{
                    "title": "p1",
                    "raw_url": "https://cj/1",
                    "suggested_price_usd": 10,
                }]},
            ),
        }
        router = _router_with(calls)
        agent = SearchAgent(router=router)
        hits = agent.search("cozy lamp")
        sources = {h.source for h in hits}
        assert "serper" in sources
        assert "cj_dropshipping" in sources

    def test_web_only_skips_products(self):
        calls = {
            "web_search": _FakeResult(
                ok=True, adapter="serper",
                data={"results": [
                    {"title": "t1", "url": "https://x/1"},
                ]},
            ),
            "sourcing_search_products": _FakeResult(
                ok=True, adapter="cj_dropshipping",
                data={"products": [
                    {"title": "p", "raw_url": "https://y"},
                ]},
            ),
        }
        router = _router_with(calls)
        agent = SearchAgent(router=router)
        hits = agent.search("x", scope=("web",))
        kinds = {h.kind for h in hits}
        assert kinds == {"web"}
        # Verify sourcing capability never queried.
        capabilities_called = [
            c.args[0].value for c in router.execute.call_args_list
        ]
        assert "web_search" in capabilities_called
        assert "sourcing_search_products" not in capabilities_called

    def test_products_only_skips_web(self):
        calls = {
            "web_search": _FakeResult(
                ok=True, adapter="serper",
                data={"results": [
                    {"title": "t", "url": "https://x"},
                ]},
            ),
            "sourcing_search_products": _FakeResult(
                ok=True, adapter="cj_dropshipping",
                data={"products": [{
                    "title": "p",
                    "raw_url": "https://y",
                }]},
            ),
        }
        router = _router_with(calls)
        agent = SearchAgent(router=router)
        hits = agent.search("x", scope=("products",))
        assert all(h.kind == "product" for h in hits)


# ── Result normalisation ───────────────────────────────────


class TestNormalisation:
    def test_web_result_shape(self):
        router = _router_with({
            "web_search": _FakeResult(
                ok=True, adapter="serper",
                data={"results": [{
                    "title": "Cozy Lamp Review",
                    "url": "https://blog.x/cozy",
                    "snippet": "Best lamps of 2026",
                }]},
            ),
        })
        agent = SearchAgent(router=router)
        hits = agent.search("cozy", scope=("web",))
        h = hits[0]
        assert h.source == "serper"
        assert h.kind == "web"
        assert h.title == "Cozy Lamp Review"
        assert h.url == "https://blog.x/cozy"
        assert h.snippet == "Best lamps of 2026"
        assert h.price_usd == 0.0

    def test_product_result_shape(self):
        router = _router_with({
            "sourcing_search_products": _FakeResult(
                ok=True, adapter="cj_dropshipping",
                data={"products": [{
                    "title": "Mushroom Lamp",
                    "raw_url": "https://cj/mush",
                    "description": "cozy wellness glow",
                    "images": ["https://cdn/img.jpg"],
                    "suggested_price_usd": 12.50,
                    "source": "cj_dropshipping",
                }]},
            ),
        })
        agent = SearchAgent(router=router)
        hits = agent.search("mushroom", scope=("products",))
        h = hits[0]
        assert h.source == "cj_dropshipping"
        assert h.kind == "product"
        assert h.price_usd == 12.50
        assert h.image_url == "https://cdn/img.jpg"
        assert h.snippet.startswith("cozy wellness")

    def test_web_result_missing_url_skipped(self):
        router = _router_with({
            "web_search": _FakeResult(
                ok=True, adapter="serper",
                data={"results": [
                    {"title": "no url"},
                    {"title": "ok", "url": "https://ok"},
                ]},
            ),
        })
        agent = SearchAgent(router=router)
        hits = agent.search("x", scope=("web",))
        assert len(hits) == 1
        assert hits[0].url == "https://ok"

    def test_product_missing_price_defaults_zero(self):
        router = _router_with({
            "sourcing_search_products": _FakeResult(
                ok=True, adapter="cj_dropshipping",
                data={"products": [
                    {"title": "t", "raw_url": "https://y"},
                ]},
            ),
        })
        agent = SearchAgent(router=router)
        hits = agent.search("x", scope=("products",))
        assert hits[0].price_usd == 0.0


# ── Dedup + rank ────────────────────────────────────────────


class TestDedup:
    def test_duplicate_url_collapsed_higher_score_kept(self):
        """Same URL appearing on two sources — only one hit
        in the output."""
        router = _router_with({
            "web_search": _FakeResult(
                ok=True, adapter="ddgs",  # lower weight 0.85
                data={"results": [
                    {"title": "From web", "url": "https://x/1"},
                ]},
            ),
            "sourcing_search_products": _FakeResult(
                ok=True, adapter="cj_dropshipping",  # 1.20
                data={"products": [{
                    "title": "From cj", "raw_url": "https://x/1",
                }]},
            ),
        })
        agent = SearchAgent(router=router)
        hits = agent.search("x")
        assert len(hits) == 1
        # Higher-score (cj_dropshipping) wins.
        assert hits[0].source == "cj_dropshipping"
        assert hits[0].title == "From cj"

    def test_results_sorted_by_score_desc(self):
        router = _router_with({
            "web_search": _FakeResult(
                ok=True, adapter="serper",
                data={"results": [
                    {"title": "A", "url": "https://1"},
                    {"title": "B", "url": "https://2"},
                    {"title": "C", "url": "https://3"},
                ]},
            ),
        })
        agent = SearchAgent(router=router)
        hits = agent.search("x", scope=("web",))
        scores = [h.score for h in hits]
        assert scores == sorted(scores, reverse=True)


# ── Failure handling ───────────────────────────────────────


class TestFailureIsolation:
    def test_web_failure_does_not_break_products(self):
        router = MagicMock()

        def execute(capability, params):
            if capability.value == "web_search":
                raise RuntimeError("boom")
            return _FakeResult(
                ok=True, adapter="cj_dropshipping",
                data={"products": [{
                    "title": "p", "raw_url": "https://y",
                }]},
            )

        router.execute.side_effect = execute
        agent = SearchAgent(router=router)
        hits = agent.search("x")
        # Web side failed silently; product side still returned.
        assert len(hits) == 1
        assert hits[0].kind == "product"

    def test_not_ok_result_skipped(self):
        router = _router_with({
            "web_search": _FakeResult(
                ok=False, error=RuntimeError("unconfigured"),
            ),
            "sourcing_search_products": _FakeResult(
                ok=True, adapter="cj_dropshipping",
                data={"products": [
                    {"title": "p", "raw_url": "https://y"},
                ]},
            ),
        })
        agent = SearchAgent(router=router)
        hits = agent.search("x")
        assert len(hits) == 1
        assert hits[0].source == "cj_dropshipping"
