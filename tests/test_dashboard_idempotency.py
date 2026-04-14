"""Dashboard idempotency endpoint — Option V phase 3.

Tests the ``_collect_idempotency_snapshot`` rollup and the
``/api/idempotency`` handler wiring.
"""
from __future__ import annotations

import pytest

from core.adapters.base import AdapterResult, Capability
from core.adapters.idempotency import (
    IdempotencyCache,
    IdempotencyPolicy,
    reset_idempotency_cache,
)
from dashboard import app as dash
from dashboard.app import (
    DashboardAPIHandler,
    _collect_idempotency_snapshot,
)


def _handler() -> DashboardAPIHandler:
    return object.__new__(DashboardAPIHandler)


def _ok(adapter="a", cap=Capability.CHAT_COMPLETE):
    return AdapterResult.success(
        adapter=adapter, capability=cap.value, data={"text": "hi"},
    )


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_idempotency_cache()
    yield
    reset_idempotency_cache()


class TestCollectIdempotencySnapshot:
    def test_empty_cache_reports_zero_counters(self, monkeypatch):
        cache = IdempotencyCache(policies={})
        monkeypatch.setattr(
            "core.adapters.idempotency.get_idempotency_cache",
            lambda: cache,
        )
        snap = _collect_idempotency_snapshot()
        assert snap["counters"]["hits"] == 0
        assert snap["counters"]["misses"] == 0
        assert snap["hit_rate"] == 0.0
        assert snap["size"] == 0
        assert snap["rows"] == []

    def test_rows_include_policy_and_live_counts(self, monkeypatch):
        cache = IdempotencyCache(policies={
            Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=5.0),
            Capability.WEB_SEARCH: IdempotencyPolicy(
                ttl_s=300.0, shared_across_adapters=True,
            ),
        })
        cache.store("a", Capability.CHAT_COMPLETE, {"p": 1}, _ok())
        cache.store("a", Capability.CHAT_COMPLETE, {"p": 2}, _ok())
        cache.store(
            "b", Capability.WEB_SEARCH, {"q": "x"},
            _ok(cap=Capability.WEB_SEARCH),
        )
        monkeypatch.setattr(
            "core.adapters.idempotency.get_idempotency_cache",
            lambda: cache,
        )
        snap = _collect_idempotency_snapshot()
        by_cap = {r["capability"]: r for r in snap["rows"]}
        chat = by_cap[Capability.CHAT_COMPLETE.value]
        assert chat["ttl_s"] == 5.0
        assert chat["live"] == 2
        assert chat["enabled"] is True
        assert chat["shared_across_adapters"] is False
        search = by_cap[Capability.WEB_SEARCH.value]
        assert search["shared_across_adapters"] is True
        assert search["live"] == 1

    def test_rows_sorted_by_live_desc(self, monkeypatch):
        cache = IdempotencyCache(policies={
            Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=5.0),
            Capability.EMBED_TEXT: IdempotencyPolicy(ttl_s=5.0),
        })
        # More entries under EMBED_TEXT → should come first.
        cache.store(
            "a", Capability.CHAT_COMPLETE, {"p": 1},
            _ok(cap=Capability.CHAT_COMPLETE),
        )
        for i in range(3):
            cache.store(
                "a", Capability.EMBED_TEXT, {"i": i},
                _ok(cap=Capability.EMBED_TEXT),
            )
        monkeypatch.setattr(
            "core.adapters.idempotency.get_idempotency_cache",
            lambda: cache,
        )
        snap = _collect_idempotency_snapshot()
        assert snap["rows"][0]["capability"] == Capability.EMBED_TEXT.value

    def test_hit_rate_reflects_counters(self, monkeypatch):
        cache = IdempotencyCache(policies={
            Capability.CHAT_COMPLETE: IdempotencyPolicy(ttl_s=60.0),
        })
        cache.store("a", Capability.CHAT_COMPLETE, {"p": 1}, _ok())
        cache.get("a", Capability.CHAT_COMPLETE, {"p": 1})  # hit
        cache.get("a", Capability.CHAT_COMPLETE, {"p": 2})  # miss
        monkeypatch.setattr(
            "core.adapters.idempotency.get_idempotency_cache",
            lambda: cache,
        )
        snap = _collect_idempotency_snapshot()
        assert snap["counters"]["hits"] == 1
        assert snap["counters"]["misses"] == 1
        assert snap["hit_rate"] == pytest.approx(0.5, abs=1e-3)


class TestIdempotencyEndpoint:
    def test_api_idempotency_wraps_snapshot(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)
        monkeypatch.setattr(
            dash, "_collect_idempotency_snapshot",
            lambda: {
                "timestamp": 1.0,
                "counters": {
                    "hits": 5, "misses": 2, "stores": 3,
                    "evictions": 0, "skipped": 1,
                },
                "hit_rate": 0.7143,
                "size": 3,
                "live": 3,
                "max_entries": 1024,
                "rows": [],
            },
        )
        h._api_idempotency()
        assert captured["status"] == 200
        assert captured["payload"]["counters"]["hits"] == 5
        assert captured["payload"]["hit_rate"] == pytest.approx(0.7143)

    def test_api_idempotency_handles_collector_failure(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)

        def _boom():
            raise RuntimeError("cache gone")

        monkeypatch.setattr(dash, "_collect_idempotency_snapshot", _boom)
        h._api_idempotency()
        assert captured["status"] == 200
        assert captured["payload"]["counters"]["hits"] == 0
        assert "error" in captured["payload"]
