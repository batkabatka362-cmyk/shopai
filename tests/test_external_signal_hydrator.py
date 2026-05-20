"""Tests for ``engines._external_signal_hydrator``.

Companion to the shopify_hydrator test suite. Coverage:

  1. Pass-through when ``supplied`` is non-empty.
  2. Empty query AND empty niche -> empty result (caller decides).
  3. Niche-only -> auto-built query.
  4. Explicit query overrides niche.
  5. Router unavailable -> empty (graceful degrade).
  6. Router returns ok=False -> empty.
  7. Router raises -> empty.
  8. Search hits normalised to competitor dict shape.
  9. Domain dedup (www. / shop. / m. variants collapse).
  10. Sub-domain stripping (shop.example.com -> example.com).
  11. max_results clamped (out-of-range values).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from engines._external_signal_hydrator import (
    hydrate_competitors_via_search,
)


def _ok(data):
    return SimpleNamespace(ok=True, data=data, error=None)


def _fail(error="x"):
    return SimpleNamespace(ok=False, data=None, error=error)


def _hit(title, url, snippet="", source="ddgs"):
    return {
        "title": title, "url": url, "snippet": snippet,
        "source": source, "retrieved_at": "",
    }


class TestPassThrough:

    def test_supplied_nonempty_skips_router(self):
        preset = [{"id": "x", "name": "X"}]
        # No router patch -- if hydrator tried to call the
        # router this would crash on AttributeError. We rely
        # on pass-through.
        out = hydrate_competitors_via_search(
            supplied=preset,
            query="ignored",
        )
        assert out == preset


class TestQueryResolution:

    def test_empty_query_and_niche_returns_empty(self):
        out = hydrate_competitors_via_search(
            supplied=None, query=None, niche=None,
        )
        assert out == []

    def test_explicit_query_used(self):
        captured = {}

        def _exec(cap, params):
            captured.update(params)
            return _ok({"results": []})

        router = SimpleNamespace(execute=_exec)
        with patch("core.adapters.get_router", return_value=router):
            hydrate_competitors_via_search(
                supplied=None,
                query="LED facial device competitors",
            )
        assert captured["query"] == "LED facial device competitors"

    def test_niche_only_builds_query(self):
        captured = {}

        def _exec(cap, params):
            captured.update(params)
            return _ok({"results": []})

        router = SimpleNamespace(execute=_exec)
        with patch("core.adapters.get_router", return_value=router):
            hydrate_competitors_via_search(
                supplied=None, niche="skincare",
            )
        assert "skincare" in captured["query"]
        assert "competitors" in captured["query"]


class TestGracefulDegrade:

    def test_router_import_failure_returns_empty(self):
        with patch(
            "core.adapters.get_router",
            side_effect=ImportError("missing"),
        ):
            out = hydrate_competitors_via_search(
                supplied=None, query="x",
            )
        assert out == []

    def test_router_not_ok_returns_empty(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate limited"),
        )
        with patch("core.adapters.get_router", return_value=router):
            out = hydrate_competitors_via_search(
                supplied=None, query="x",
            )
        assert out == []

    def test_router_raises_returns_empty(self):
        def _raises(c, p):
            raise RuntimeError("boom")
        router = SimpleNamespace(execute=_raises)
        with patch("core.adapters.get_router", return_value=router):
            out = hydrate_competitors_via_search(
                supplied=None, query="x",
            )
        assert out == []


class TestNormalisation:

    def test_search_hits_become_competitors(self):
        router = SimpleNamespace(execute=lambda c, p: _ok({
            "results": [
                _hit(
                    "Glow Labs - LED Therapy Devices",
                    "https://glowlabs.com/products/lifter",
                    "Pro-grade LED facial...",
                ),
                _hit(
                    "Acme Skincare",
                    "https://acmeskincare.com/lifter",
                    "Salon-quality at-home...",
                ),
            ],
        }))
        with patch("core.adapters.get_router", return_value=router):
            out = hydrate_competitors_via_search(
                supplied=None, query="LED facial",
            )
        assert len(out) == 2
        first = out[0]
        # Shape carries id (domain) + url + snippet
        assert first["domain"] == "glowlabs.com"
        assert first["id"] == "glowlabs.com"
        assert first["url"].startswith("https://")
        assert "LED" in first["snippet"]
        # Downstream-required default fields present
        assert first["prices"] == {}
        assert first["product_count"] == 0
        # source_query stored for audit
        assert first["source_query"] == "LED facial"


class TestDedup:

    def test_www_subdomain_dedupes(self):
        router = SimpleNamespace(execute=lambda c, p: _ok({
            "results": [
                _hit("Page 1", "https://www.example.com/a"),
                _hit("Page 2", "https://example.com/b"),
                _hit("Page 3", "https://shop.example.com/c"),
            ],
        }))
        with patch("core.adapters.get_router", return_value=router):
            out = hydrate_competitors_via_search(
                supplied=None, query="x",
            )
        # All 3 hits collapse to the same domain
        assert len(out) == 1
        assert out[0]["domain"] == "example.com"

    def test_distinct_domains_preserved(self):
        router = SimpleNamespace(execute=lambda c, p: _ok({
            "results": [
                _hit("A", "https://a.com/p"),
                _hit("B", "https://b.com/p"),
                _hit("C", "https://c.com/p"),
            ],
        }))
        with patch("core.adapters.get_router", return_value=router):
            out = hydrate_competitors_via_search(
                supplied=None, query="x",
            )
        assert {c["domain"] for c in out} == {"a.com", "b.com", "c.com"}


class TestMaxResultsClamp:

    def test_zero_falls_back_to_default(self):
        """``max_results=0`` is falsy -> default 10."""
        captured = {}

        def _exec(cap, params):
            captured.update(params)
            return _ok({"results": []})

        router = SimpleNamespace(execute=_exec)
        with patch("core.adapters.get_router", return_value=router):
            hydrate_competitors_via_search(
                supplied=None, query="x", max_results=0,
            )
        assert captured["max_results"] == 10

    def test_clamps_negative_to_min(self):
        """Explicit negative value clamps to floor 1."""
        captured = {}

        def _exec(cap, params):
            captured.update(params)
            return _ok({"results": []})

        router = SimpleNamespace(execute=_exec)
        with patch("core.adapters.get_router", return_value=router):
            hydrate_competitors_via_search(
                supplied=None, query="x", max_results=-5,
            )
        assert captured["max_results"] == 1

    def test_clamps_above_max(self):
        captured = {}

        def _exec(cap, params):
            captured.update(params)
            return _ok({"results": []})

        router = SimpleNamespace(execute=_exec)
        with patch("core.adapters.get_router", return_value=router):
            hydrate_competitors_via_search(
                supplied=None, query="x", max_results=10_000,
            )
        # Clamp ceiling = 20
        assert captured["max_results"] == 20


class TestMalformedHitTolerance:

    def test_non_dict_hits_skipped(self):
        router = SimpleNamespace(execute=lambda c, p: _ok({
            "results": [
                "garbage string",
                42,
                _hit("Real", "https://real.com/p"),
            ],
        }))
        with patch("core.adapters.get_router", return_value=router):
            out = hydrate_competitors_via_search(
                supplied=None, query="x",
            )
        assert len(out) == 1
        assert out[0]["domain"] == "real.com"

    def test_hit_without_url_skipped(self):
        router = SimpleNamespace(execute=lambda c, p: _ok({
            "results": [
                {"title": "No URL", "url": ""},
                _hit("Real", "https://real.com/p"),
            ],
        }))
        with patch("core.adapters.get_router", return_value=router):
            out = hydrate_competitors_via_search(
                supplied=None, query="x",
            )
        assert len(out) == 1
