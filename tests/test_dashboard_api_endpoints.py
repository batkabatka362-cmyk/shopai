"""Wave 5 #B: symmetric operator endpoints on the dashboard API.

Wave 4 shipped three observability gains that were invisible
from HTTP:

* Wave 4 #4 — Mind.cognitive_report() (in-memory dispatcher
  counters + per-cycle audit trace)
* Wave 4 #2 — SatelliteRouter layer stats (vector / graph /
  signal totals)
* Wave 2 #1 — PolicyStore JSONL audit log (HARD / MEDIUM /
  SOFT decisions)

This wave exposes all three over HTTP so operators can watch
them from curl. Every endpoint must fail soft — a missing or
crashing subsystem returns an ``{"error": "..."}`` envelope,
never a 500, and ``/api/status`` never crashes the dashboard.

Tests below cover:

* Happy path for each endpoint — correct keys, timestamps,
  singleton pass-through
* ``?limit=N`` querystring parsing on ``/api/policy/audit``
  including clamp + malformed fallback
* Fail-soft behaviour when the underlying import or singleton
  raises — the dashboard must still respond
* _parse_limit edge cases in isolation (unit test)
"""
from __future__ import annotations

from typing import Any

import pytest

from api.dashboard_api import DashboardAPIHandler


# ---------------------------------------------------------------------------
# _parse_limit — pure helper
# ---------------------------------------------------------------------------


class TestParseLimit:
    def test_empty_string_returns_default(self):
        assert DashboardAPIHandler._parse_limit("", default=20, maximum=500) == 20

    def test_missing_limit_key_returns_default(self):
        assert DashboardAPIHandler._parse_limit(
            "foo=bar", default=15, maximum=500,
        ) == 15

    def test_valid_limit_parsed(self):
        assert DashboardAPIHandler._parse_limit(
            "limit=42", default=20, maximum=500,
        ) == 42

    def test_limit_clamped_to_maximum(self):
        assert DashboardAPIHandler._parse_limit(
            "limit=9999", default=20, maximum=500,
        ) == 500

    def test_limit_clamped_to_one_minimum(self):
        assert DashboardAPIHandler._parse_limit(
            "limit=0", default=20, maximum=500,
        ) == 1
        assert DashboardAPIHandler._parse_limit(
            "limit=-5", default=20, maximum=500,
        ) == 1

    def test_non_integer_limit_falls_back_to_default(self):
        assert DashboardAPIHandler._parse_limit(
            "limit=not_a_number", default=20, maximum=500,
        ) == 20

    def test_limit_in_multi_key_querystring(self):
        assert DashboardAPIHandler._parse_limit(
            "foo=bar&limit=7&baz=qux", default=20, maximum=500,
        ) == 7

    def test_malformed_querystring_returns_default(self):
        # A key with no = is skipped, not raised
        assert DashboardAPIHandler._parse_limit(
            "nokey&limit=3", default=20, maximum=500,
        ) == 3


# ---------------------------------------------------------------------------
# /api/cognitive — Mind dispatcher stats
# ---------------------------------------------------------------------------


class _FakeMind:
    def __init__(self, report: dict[str, Any]) -> None:
        self._report = report

    def cognitive_report(self) -> dict[str, Any]:
        return dict(self._report)


class TestCognitiveEndpoint:
    def test_returns_mind_cognitive_report_plus_timestamp(self, monkeypatch):
        fake = _FakeMind({
            "cycles_run": 3,
            "counts":     {"Si": 3, "Ni": 3},
            "errors":     {},
            "recent":     [],
            "registered": ["Si", "Ni"],
            "total":      6,
        })
        monkeypatch.setattr(
            "core.cognitive.mind.get_mind", lambda: fake,
        )
        out = DashboardAPIHandler._get_cognitive_report()
        assert out["cycles_run"] == 3
        assert out["counts"] == {"Si": 3, "Ni": 3}
        assert out["total"] == 6
        assert "timestamp" in out
        assert isinstance(out["timestamp"], float)

    def test_fails_soft_when_get_mind_raises(self, monkeypatch):
        def _boom():
            raise RuntimeError("mind offline")
        monkeypatch.setattr(
            "core.cognitive.mind.get_mind", _boom,
        )
        out = DashboardAPIHandler._get_cognitive_report()
        assert "error" in out
        assert "mind offline" in out["error"]

    def test_fails_soft_when_report_raises(self, monkeypatch):
        class _CrashyMind:
            def cognitive_report(self):
                raise ValueError("report broke")
        monkeypatch.setattr(
            "core.cognitive.mind.get_mind", lambda: _CrashyMind(),
        )
        out = DashboardAPIHandler._get_cognitive_report()
        assert "error" in out
        assert "report broke" in out["error"]


# ---------------------------------------------------------------------------
# /api/memory/satellites — SatelliteRouter stats
# ---------------------------------------------------------------------------


class _FakeRouter:
    def __init__(self, stats: dict[str, Any]) -> None:
        self._stats = stats

    def stats(self) -> dict[str, Any]:
        return dict(self._stats)


class _FakeUnifiedMemory:
    def __init__(self, router: Any) -> None:
        self._router = router

    def get_satellites(self) -> Any:
        return self._router


class TestSatelliteEndpoint:
    def test_returns_layer_stats_plus_timestamp(self, monkeypatch):
        router = _FakeRouter({
            "vector": {"total": 42, "enabled": True},
            "graph":  {"nodes": 10, "edges": 7, "enabled": True},
            "signal": {"series": 3, "enabled": True},
        })
        mem = _FakeUnifiedMemory(router)
        monkeypatch.setattr(
            "core.memory.unified_memory.get_unified_memory", lambda: mem,
        )
        out = DashboardAPIHandler._get_satellite_stats()
        assert "layers" in out
        assert out["layers"]["vector"]["total"] == 42
        assert out["layers"]["graph"]["nodes"] == 10
        assert out["layers"]["signal"]["series"] == 3
        assert "timestamp" in out

    def test_fails_soft_when_get_unified_memory_raises(self, monkeypatch):
        def _boom():
            raise RuntimeError("memory down")
        monkeypatch.setattr(
            "core.memory.unified_memory.get_unified_memory", _boom,
        )
        out = DashboardAPIHandler._get_satellite_stats()
        assert "error" in out
        assert "memory down" in out["error"]

    def test_fails_soft_when_router_stats_raises(self, monkeypatch):
        class _CrashyRouter:
            def stats(self):
                raise RuntimeError("stats blew up")
        mem = _FakeUnifiedMemory(_CrashyRouter())
        monkeypatch.setattr(
            "core.memory.unified_memory.get_unified_memory", lambda: mem,
        )
        out = DashboardAPIHandler._get_satellite_stats()
        assert "error" in out
        assert "stats blew up" in out["error"]

    def test_returns_real_shape_from_live_singleton(self):
        """End-to-end check against the real UnifiedMemory singleton.

        The layers may be disabled in a stripped-down deployment —
        we only assert the shape, not the values.
        """
        out = DashboardAPIHandler._get_satellite_stats()
        # Either the happy path or the error envelope — both are
        # valid responses. If it's the happy path, assert shape.
        if "error" not in out:
            assert "layers" in out
            assert "timestamp" in out
            assert set(out["layers"].keys()) >= {"vector", "graph", "signal"}


# ---------------------------------------------------------------------------
# /api/policy/audit — JSONL audit tail
# ---------------------------------------------------------------------------


class _FakeStore:
    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._entries = entries
        self.last_limit: int | None = None

    def read_audit(self, limit: int = 20) -> list[dict[str, Any]]:
        self.last_limit = limit
        return list(self._entries[:limit])


class TestPolicyAuditEndpoint:
    def test_returns_entries_count_and_timestamp(self, monkeypatch):
        store = _FakeStore([
            {"rule_id": "r1", "verdict": "ALLOW"},
            {"rule_id": "r2", "verdict": "BLOCK"},
            {"rule_id": "r3", "verdict": "ALLOW"},
        ])
        monkeypatch.setattr(
            "engines.meta_governance.policy_store.get_default_store",
            lambda: store,
        )
        out = DashboardAPIHandler._get_policy_audit(limit=20)
        assert out["count"] == 3
        assert len(out["entries"]) == 3
        assert out["entries"][0]["rule_id"] == "r1"
        assert "timestamp" in out
        assert store.last_limit == 20

    def test_limit_is_forwarded_to_store(self, monkeypatch):
        store = _FakeStore([
            {"rule_id": f"r{i}"} for i in range(50)
        ])
        monkeypatch.setattr(
            "engines.meta_governance.policy_store.get_default_store",
            lambda: store,
        )
        out = DashboardAPIHandler._get_policy_audit(limit=5)
        assert store.last_limit == 5
        assert out["count"] == 5

    def test_fails_soft_when_store_raises(self, monkeypatch):
        def _boom():
            raise RuntimeError("audit unavailable")
        monkeypatch.setattr(
            "engines.meta_governance.policy_store.get_default_store",
            _boom,
        )
        out = DashboardAPIHandler._get_policy_audit(limit=20)
        assert "error" in out
        assert "audit unavailable" in out["error"]

    def test_fails_soft_when_read_audit_raises(self, monkeypatch):
        class _CrashyStore:
            def read_audit(self, limit: int = 20):
                raise RuntimeError("disk error")
        monkeypatch.setattr(
            "engines.meta_governance.policy_store.get_default_store",
            lambda: _CrashyStore(),
        )
        out = DashboardAPIHandler._get_policy_audit(limit=20)
        assert "error" in out
        assert "disk error" in out["error"]

    def test_empty_audit_returns_zero_count(self, monkeypatch):
        monkeypatch.setattr(
            "engines.meta_governance.policy_store.get_default_store",
            lambda: _FakeStore([]),
        )
        out = DashboardAPIHandler._get_policy_audit(limit=20)
        assert out["count"] == 0
        assert out["entries"] == []
        assert "timestamp" in out
