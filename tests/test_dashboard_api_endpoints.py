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


# ---------------------------------------------------------------------------
# Wave 6 #5: /api/beliefs — Bayesian posterior snapshot
# ---------------------------------------------------------------------------


class _FakeBeliefStore:
    """In-memory stub for the belief store that matches the surface
    the endpoint uses: ``snapshot()`` + ``credible_interval_95``.
    """

    def __init__(self, rows: dict[str, dict[str, float]],
                 intervals: dict[str, tuple[float, float]] | None = None):
        self._rows = rows
        self._intervals = intervals or {}

    def snapshot(self) -> dict[str, dict[str, float]]:
        return dict(self._rows)

    def credible_interval_95(self, key: str) -> tuple[float, float]:
        return self._intervals.get(key, (0.0, 1.0))


class TestBeliefEndpoint:
    def test_empty_store_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            "core.mentality.get_default_belief_store",
            lambda: _FakeBeliefStore({}),
        )
        out = DashboardAPIHandler._get_belief_snapshot(limit=50)
        assert out["beliefs"] == []
        assert out["count"] == 0
        assert out["total"] == 0
        assert "timestamp" in out

    def test_returns_rows_with_enriched_fields(self, monkeypatch):
        rows = {
            "shopify::pricing.update": {
                "alpha": 8.0, "beta": 4.0, "mean": 8 / 12, "n": 10,
            },
            "shopify::product.create_listing": {
                "alpha": 15.0, "beta": 1.0, "mean": 15 / 16, "n": 14,
            },
        }
        intervals = {
            "shopify::pricing.update":            (0.40, 0.85),
            "shopify::product.create_listing":    (0.78, 0.99),
        }
        monkeypatch.setattr(
            "core.mentality.get_default_belief_store",
            lambda: _FakeBeliefStore(rows, intervals),
        )
        out = DashboardAPIHandler._get_belief_snapshot(limit=50)
        assert out["count"] == 2
        assert out["total"] == 2
        # Sorted by ci_low ascending — pricing.update (0.40)
        # must come before product.create_listing (0.78)
        assert out["beliefs"][0]["key"] == "shopify::pricing.update"
        assert out["beliefs"][0]["ci_low"] == 0.40
        assert out["beliefs"][0]["ci_high"] == 0.85
        assert out["beliefs"][0]["n"] == 10
        assert out["beliefs"][1]["key"] == "shopify::product.create_listing"

    def test_limit_truncates_result_and_preserves_total(self, monkeypatch):
        rows = {
            f"t::k{i}": {"alpha": 2.0, "beta": float(i + 1),
                         "mean": 2.0 / (2.0 + i + 1), "n": i + 1}
            for i in range(10)
        }
        monkeypatch.setattr(
            "core.mentality.get_default_belief_store",
            lambda: _FakeBeliefStore(rows),
        )
        out = DashboardAPIHandler._get_belief_snapshot(limit=3)
        assert out["count"] == 3
        assert out["total"] == 10
        assert len(out["beliefs"]) == 3

    def test_sort_breaks_ties_by_mean_then_n_descending(self, monkeypatch):
        rows = {
            "small_n": {"alpha": 1.0, "beta": 3.0, "mean": 0.25, "n": 2},
            "big_n":   {"alpha": 5.0, "beta": 15.0, "mean": 0.25, "n": 18},
        }
        intervals = {"small_n": (0.0, 0.7), "big_n": (0.0, 0.7)}
        monkeypatch.setattr(
            "core.mentality.get_default_belief_store",
            lambda: _FakeBeliefStore(rows, intervals),
        )
        out = DashboardAPIHandler._get_belief_snapshot(limit=50)
        # Same ci_low, same mean — higher n wins the tiebreak
        # (better-evidenced bad keys rank above thinly-evidenced ones).
        assert out["beliefs"][0]["key"] == "big_n"
        assert out["beliefs"][1]["key"] == "small_n"

    def test_fails_soft_when_store_access_raises(self, monkeypatch):
        def _boom():
            raise RuntimeError("belief store offline")
        monkeypatch.setattr(
            "core.mentality.get_default_belief_store", _boom,
        )
        out = DashboardAPIHandler._get_belief_snapshot(limit=50)
        assert "error" in out
        assert "belief store offline" in out["error"]

    def test_fails_soft_when_snapshot_raises(self, monkeypatch):
        class _CrashyStore:
            def snapshot(self):
                raise RuntimeError("snapshot broken")
        monkeypatch.setattr(
            "core.mentality.get_default_belief_store",
            lambda: _CrashyStore(),
        )
        out = DashboardAPIHandler._get_belief_snapshot(limit=50)
        assert "error" in out

    def test_interval_raise_falls_back_to_wide_band(self, monkeypatch):
        class _PartialStore:
            def snapshot(self):
                return {"k": {"alpha": 2.0, "beta": 3.0,
                              "mean": 0.4, "n": 3}}
            def credible_interval_95(self, key):
                raise RuntimeError("interval math broken")
        monkeypatch.setattr(
            "core.mentality.get_default_belief_store",
            lambda: _PartialStore(),
        )
        out = DashboardAPIHandler._get_belief_snapshot(limit=50)
        assert out["count"] == 1
        assert out["beliefs"][0]["ci_low"] == 0.0
        assert out["beliefs"][0]["ci_high"] == 1.0

    # -- Wave 6 #12: decay telemetry ---------------------------------

    def test_envelope_surfaces_half_life_when_store_has_none(
        self, monkeypatch,
    ):
        """Decay disabled → ``half_life_seconds`` is ``None`` at
        the envelope level so the dashboard can render "decay
        off" explicitly."""
        monkeypatch.setattr(
            "core.mentality.get_default_belief_store",
            lambda: _FakeBeliefStore({}),
        )
        out = DashboardAPIHandler._get_belief_snapshot(limit=50)
        assert "half_life_seconds" in out
        assert out["half_life_seconds"] is None

    def test_envelope_surfaces_half_life_when_store_has_it(
        self, monkeypatch,
    ):
        class _DecayStore(_FakeBeliefStore):
            half_life_seconds = 3600.0

        monkeypatch.setattr(
            "core.mentality.get_default_belief_store",
            lambda: _DecayStore({}),
        )
        out = DashboardAPIHandler._get_belief_snapshot(limit=50)
        assert out["half_life_seconds"] == 3600.0

    def test_rows_include_last_updated_at_and_age_seconds(
        self, monkeypatch,
    ):
        """Snapshot rows carry ``last_updated_at`` — the endpoint
        forwards it and adds a derived ``age_seconds``."""
        import time as _time

        now = _time.time()
        rows = {
            "fresh": {
                "alpha": 5.0, "beta": 1.0, "mean": 5 / 6, "n": 4,
                "last_updated_at": now - 10.0,
            },
            "stale": {
                "alpha": 2.0, "beta": 8.0, "mean": 0.2, "n": 8,
                "last_updated_at": now - 10_000.0,
            },
        }
        intervals = {
            "fresh": (0.50, 0.95),
            "stale": (0.05, 0.40),
        }
        monkeypatch.setattr(
            "core.mentality.get_default_belief_store",
            lambda: _FakeBeliefStore(rows, intervals),
        )
        out = DashboardAPIHandler._get_belief_snapshot(limit=50)
        by_key = {r["key"]: r for r in out["beliefs"]}
        assert by_key["fresh"]["last_updated_at"] == rows["fresh"][
            "last_updated_at"
        ]
        # Age is clock-sensitive — compare with a generous window.
        assert 9.0 <= by_key["fresh"]["age_seconds"] <= 30.0
        assert 9_995.0 <= by_key["stale"]["age_seconds"] <= 10_030.0

    def test_row_missing_last_updated_at_falls_back_to_none(
        self, monkeypatch,
    ):
        """Legacy rows without ``last_updated_at`` must still work
        — the endpoint reports ``None`` for both the timestamp and
        the derived age."""
        rows = {
            "legacy": {"alpha": 3.0, "beta": 3.0, "mean": 0.5, "n": 4},
        }
        monkeypatch.setattr(
            "core.mentality.get_default_belief_store",
            lambda: _FakeBeliefStore(rows),
        )
        out = DashboardAPIHandler._get_belief_snapshot(limit=50)
        row = out["beliefs"][0]
        assert row["last_updated_at"] is None
        assert row["age_seconds"] is None

    def test_age_seconds_never_negative_on_clock_skew(
        self, monkeypatch,
    ):
        """If ``last_updated_at`` is in the future (clock skew or
        a paused test clock), age should clamp to zero rather than
        leak a negative into the dashboard."""
        import time as _time

        rows = {
            "future": {
                "alpha": 2.0, "beta": 2.0, "mean": 0.5, "n": 2,
                "last_updated_at": _time.time() + 1_000.0,
            },
        }
        monkeypatch.setattr(
            "core.mentality.get_default_belief_store",
            lambda: _FakeBeliefStore(rows),
        )
        out = DashboardAPIHandler._get_belief_snapshot(limit=50)
        assert out["beliefs"][0]["age_seconds"] == 0.0

    def test_malformed_last_updated_at_falls_back_to_none(
        self, monkeypatch,
    ):
        rows = {
            "bad": {
                "alpha": 2.0, "beta": 2.0, "mean": 0.5, "n": 2,
                "last_updated_at": "not-a-timestamp",
            },
        }
        monkeypatch.setattr(
            "core.mentality.get_default_belief_store",
            lambda: _FakeBeliefStore(rows),
        )
        out = DashboardAPIHandler._get_belief_snapshot(limit=50)
        # The raw field round-trips even if invalid, but the
        # derived age drops to None so the dashboard doesn't
        # render bogus seconds.
        assert out["beliefs"][0]["age_seconds"] is None

    def test_end_to_end_with_real_store(self, monkeypatch, tmp_path):
        """Smoke test: feed the real BeliefStore some outcomes
        via the singleton and read them back through the endpoint."""
        from core.mentality import (
            BeliefStore,
            reset_default_belief_store,
            set_default_belief_store,
        )

        set_default_belief_store(
            BeliefStore(persist_path=tmp_path / "b.json"),
        )
        try:
            from core.mentality import get_default_belief_store
            store = get_default_belief_store()
            for _ in range(5):
                store.observe("shop::x", True)
            for _ in range(5):
                store.observe("shop::y", False)
            out = DashboardAPIHandler._get_belief_snapshot(limit=50)
            assert out["total"] == 2
            keys = [row["key"] for row in out["beliefs"]]
            # shop::y has the worse posterior so it floats up.
            assert keys[0] == "shop::y"
            assert keys[1] == "shop::x"
        finally:
            reset_default_belief_store()


# ---------------------------------------------------------------------------
# Wave 6 #7: /api/reflection — learned rule snapshot
# ---------------------------------------------------------------------------


class _FakeSynth:
    """Stub matching the surface the reflection endpoint uses."""

    def __init__(self, rows: list[dict[str, Any]],
                 last_run_at: float | None = None,
                 persist_path: str = ""):
        self._rows = rows
        self.last_run_at = last_run_at
        self.persist_path = persist_path

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._rows)


class TestReflectionEndpoint:
    def test_empty_synth_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer",
            lambda: _FakeSynth([]),
        )
        out = DashboardAPIHandler._get_reflection_snapshot(limit=50)
        assert out["patterns"] == []
        assert out["count"] == 0
        assert out["total"] == 0
        assert "timestamp" in out

    def test_returns_rows_and_metadata(self, monkeypatch):
        rows = [
            {
                "signature":   "error:abc",
                "rule_id":     "learned::error:abc",
                "kind":        "error",
                "sample_text": "redis timeout on key 1",
                "occurrences": 4,
                "first_seen":  1.0,
                "last_seen":   9.0,
                "confidence":  0.8,
            },
            {
                "signature":   "error:def",
                "rule_id":     "learned::error:def",
                "kind":        "error",
                "sample_text": "ssl handshake failed",
                "occurrences": 3,
                "first_seen":  2.0,
                "last_seen":   5.0,
                "confidence":  0.75,
            },
        ]
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer",
            lambda: _FakeSynth(rows, last_run_at=42.0, persist_path="/x/l.jsonl"),
        )
        out = DashboardAPIHandler._get_reflection_snapshot(limit=50)
        assert out["count"] == 2
        assert out["total"] == 2
        assert out["last_run_at"] == 42.0
        assert out["persist_path"] == "/x/l.jsonl"
        assert out["patterns"][0]["signature"] == "error:abc"
        assert out["patterns"][0]["rule_id"] == "learned::error:abc"

    def test_limit_truncates_result_and_preserves_total(self, monkeypatch):
        rows = [
            {
                "signature":   f"error:{i}",
                "rule_id":     f"learned::error:{i}",
                "kind":        "error",
                "sample_text": f"msg {i}",
                "occurrences": 3,
                "first_seen":  0.0,
                "last_seen":   float(i),
                "confidence":  0.8,
            }
            for i in range(10)
        ]
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer",
            lambda: _FakeSynth(rows),
        )
        out = DashboardAPIHandler._get_reflection_snapshot(limit=3)
        assert out["count"] == 3
        assert out["total"] == 10
        assert len(out["patterns"]) == 3

    def test_fails_soft_when_synth_access_raises(self, monkeypatch):
        def _boom():
            raise RuntimeError("synth offline")
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer", _boom,
        )
        out = DashboardAPIHandler._get_reflection_snapshot(limit=50)
        assert "error" in out
        assert "synth offline" in out["error"]

    def test_fails_soft_when_snapshot_raises(self, monkeypatch):
        class _CrashySynth:
            last_run_at = None
            persist_path = ""
            def snapshot(self):
                raise RuntimeError("snapshot broken")
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer",
            lambda: _CrashySynth(),
        )
        out = DashboardAPIHandler._get_reflection_snapshot(limit=50)
        assert "error" in out

    def test_enriches_rows_with_policy_store_stats(self, monkeypatch):
        """Wave 6 #8: the endpoint augments each pattern with the
        matches/blocks/last_matched_at from the default policy store
        so operators can tell a useful learned rule from a dead one."""
        rows = [
            {
                "signature":   "error:abc",
                "rule_id":     "learned::error:abc",
                "kind":        "error",
                "sample_text": "something",
                "occurrences": 3,
                "first_seen":  0.0,
                "last_seen":   1.0,
                "confidence":  0.8,
            },
            {
                "signature":   "error:def",
                "rule_id":     "learned::error:def",
                "kind":        "error",
                "sample_text": "other",
                "occurrences": 3,
                "first_seen":  0.0,
                "last_seen":   0.5,
                "confidence":  0.8,
            },
        ]
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer",
            lambda: _FakeSynth(rows),
        )

        class _FakeStatsStore:
            def get_all_rule_stats(self):
                return [
                    {
                        "rule_id":         "learned::error:abc",
                        "tier":            "soft",
                        "source":          "learned",
                        "matches":         7,
                        "blocks":          5,
                        "modifications":   0,
                        "first_matched_at": 1.0,
                        "last_matched_at":  9.0,
                    },
                ]

        monkeypatch.setattr(
            "engines.meta_governance.policy_store.get_default_store",
            lambda: _FakeStatsStore(),
        )
        out = DashboardAPIHandler._get_reflection_snapshot(limit=50)
        assert out["count"] == 2
        abc = next(r for r in out["patterns"] if r["signature"] == "error:abc")
        assert abc["matches"] == 7
        assert abc["blocks"] == 5
        assert abc["last_matched_at"] == 9.0
        # def has no stats so fields default to 0/None.
        defr = next(r for r in out["patterns"] if r["signature"] == "error:def")
        assert defr["matches"] == 0
        assert defr["blocks"] == 0
        assert defr["last_matched_at"] is None

    def test_stats_store_raise_does_not_break_endpoint(self, monkeypatch):
        rows = [
            {
                "signature":   "error:abc",
                "rule_id":     "learned::error:abc",
                "kind":        "error",
                "sample_text": "m",
                "occurrences": 3,
                "first_seen":  0.0,
                "last_seen":   1.0,
                "confidence":  0.8,
            },
        ]
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer",
            lambda: _FakeSynth(rows),
        )

        def _boom():
            raise RuntimeError("store offline")
        monkeypatch.setattr(
            "engines.meta_governance.policy_store.get_default_store", _boom,
        )
        out = DashboardAPIHandler._get_reflection_snapshot(limit=50)
        assert out["count"] == 1
        assert out["patterns"][0]["matches"] == 0

    def test_end_to_end_with_real_synth(self, tmp_path):
        """Feed the real synthesizer three matching errors via a
        real PolicyStore and read the learned rule back through
        the endpoint."""
        from core.reflection.synthesizer import (
            ReflectionSynthesizer,
            reset_default_synthesizer,
            set_default_synthesizer,
        )
        from core.memory.quality_engine import MemoryRecord
        from engines.meta_governance.policy_store import PolicyStore

        ledger = tmp_path / "ledger.jsonl"
        store = PolicyStore(audit_path=str(tmp_path / "a.jsonl"))
        synth = ReflectionSynthesizer(
            policy_store=store, persist_path=ledger,
        )

        def _err(msg: str) -> MemoryRecord:
            return MemoryRecord(
                kind="error",
                quality=0.6,
                confidence=0.7,
                success_rate=0.0,
                usage=1,
                created_at=1.0,
                payload={"message": msg},
            )

        synth.run([
            _err("payment gateway timeout on order 1"),
            _err("payment gateway timeout on order 2"),
            _err("payment gateway timeout on order 3"),
        ])
        set_default_synthesizer(synth)
        try:
            out = DashboardAPIHandler._get_reflection_snapshot(limit=50)
            assert out["total"] == 1
            assert out["count"] == 1
            row = out["patterns"][0]
            assert row["kind"] == "error"
            assert row["occurrences"] == 3
            assert row["rule_id"].startswith("learned::")
            assert row["persist_path"] if "persist_path" in row else True
            assert out["persist_path"] == str(ledger)
        finally:
            reset_default_synthesizer()

    # -- Wave 6 #16: synthesizer config telemetry ---------------------

    def test_config_surfaces_tuning_parameters(self, monkeypatch):
        """The endpoint returns the synthesizer's config so
        operators can see the promotion bar."""
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer",
            lambda: _FakeSynth([]),
        )
        out = DashboardAPIHandler._get_reflection_snapshot(limit=50)
        # The fake synth lacks config(), so config should be empty
        # (fail-soft). That itself is worth testing.
        assert "config" in out

    def test_config_from_real_synth(self, tmp_path):
        from core.reflection.synthesizer import (
            ReflectionSynthesizer,
            reset_default_synthesizer,
            set_default_synthesizer,
        )
        from engines.meta_governance.policy_store import PolicyStore

        store = PolicyStore(audit_path=str(tmp_path / "a.jsonl"))
        synth = ReflectionSynthesizer(
            policy_store=store,
            min_occurrences=5,
            min_confidence=0.9,
            smoothing=2.0,
            persist_path=tmp_path / "l.jsonl",
        )
        set_default_synthesizer(synth)
        try:
            out = DashboardAPIHandler._get_reflection_snapshot(limit=50)
            cfg = out["config"]
            assert cfg["min_occurrences"] == 5
            assert cfg["min_confidence"] == 0.9
            assert cfg["smoothing"] == 2.0
            assert str(tmp_path / "l.jsonl") in cfg["persist_path"]
        finally:
            reset_default_synthesizer()

    # -- Wave 6 #14: learning stats -----------------------------------

    def test_learning_stats_present_in_response(self, monkeypatch):
        """The endpoint always returns a ``learning_stats`` dict,
        even when no patterns exist."""
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer",
            lambda: _FakeSynth([]),
        )
        out = DashboardAPIHandler._get_reflection_snapshot(limit=50)
        assert "learning_stats" in out
        stats = out["learning_stats"]
        assert stats["active_patterns"] == 0
        assert stats["firing_patterns"] == 0
        assert stats["total_matches"] == 0
        assert stats["total_blocks"] == 0
        assert stats["effectiveness"] is None  # 0 active → None
        assert stats["retention_rate"] is None

    def test_learning_stats_counts_firing_patterns(self, monkeypatch):
        rows = [
            {
                "signature":   f"error:{i}",
                "rule_id":     f"learned::error:{i}",
                "kind":        "error",
                "sample_text": f"msg {i}",
                "occurrences": 3,
                "first_seen":  0.0,
                "last_seen":   1.0,
                "confidence":  0.8,
            }
            for i in range(4)
        ]
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer",
            lambda: _FakeSynth(rows),
        )

        class _StatsStore:
            def get_all_rule_stats(self):
                return [
                    {"rule_id": "learned::error:0",
                     "matches": 3, "blocks": 2,
                     "modifications": 0,
                     "first_matched_at": 1.0,
                     "last_matched_at": 5.0},
                    {"rule_id": "learned::error:2",
                     "matches": 1, "blocks": 0,
                     "modifications": 0,
                     "first_matched_at": 2.0,
                     "last_matched_at": 3.0},
                ]
            def list_rules(self, tier=None):
                return [object()] * 3  # 3 soft rules
            def read_audit(self, limit=500):
                return [
                    {"event": "RETIREMENT", "rule_id": "learned::error:old"},
                    {"event": "RETIREMENT", "rule_id": "learned::error:old2"},
                    {"event": "PROMOTION",  "rule_id": "learned::error:0"},
                ]

        monkeypatch.setattr(
            "engines.meta_governance.policy_store.get_default_store",
            lambda: _StatsStore(),
        )
        out = DashboardAPIHandler._get_reflection_snapshot(limit=50)
        stats = out["learning_stats"]
        assert stats["active_patterns"] == 4
        assert stats["firing_patterns"] == 2  # error:0 and error:2
        assert stats["total_matches"] == 4    # 3 + 1
        assert stats["total_blocks"] == 2     # 2 + 0
        assert stats["retired_count"] == 2
        assert stats["total_promoted"] == 6   # 4 active + 2 retired
        assert stats["soft_in_store"] == 3
        assert stats["effectiveness"] == round(2 / 4, 4)
        assert stats["retention_rate"] == round(4 / 6, 4)

    def test_learning_stats_degrades_when_store_offline(self, monkeypatch):
        """When the policy store is unavailable, learning_stats
        still populates — just with zero store-side counters."""
        rows = [
            {
                "signature":   "error:a",
                "rule_id":     "learned::error:a",
                "kind":        "error",
                "sample_text": "m",
                "occurrences": 3,
                "first_seen":  0.0,
                "last_seen":   1.0,
                "confidence":  0.8,
            },
        ]
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer",
            lambda: _FakeSynth(rows),
        )

        def _boom():
            raise RuntimeError("store offline")
        monkeypatch.setattr(
            "engines.meta_governance.policy_store.get_default_store", _boom,
        )
        out = DashboardAPIHandler._get_reflection_snapshot(limit=50)
        stats = out["learning_stats"]
        assert stats["active_patterns"] == 1
        assert stats["soft_in_store"] == 0
        assert stats["retired_count"] == 0


# ---------------------------------------------------------------------------
# Wave 6 #15: learning summary on _summarise_learning
# ---------------------------------------------------------------------------


class TestLearningStatusSummary:
    """Unit tests for ``_summarise_learning()`` in isolation."""

    def test_all_subsystems_offline_returns_unknown(self, monkeypatch):
        """When every subsystem raises, the summary degrades
        gracefully to None fields + ``status=unknown``."""
        def _boom():
            raise RuntimeError("offline")
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer", _boom,
        )
        monkeypatch.setattr(
            "engines.meta_governance.policy_store.get_default_store", _boom,
        )
        monkeypatch.setattr(
            "core.mentality.get_default_belief_store", _boom,
        )
        out = DashboardAPIHandler._summarise_learning()
        assert out["active_patterns"] is None
        assert out["soft_rules"] is None
        assert out["beliefs"] is None
        assert out["status"] == "unknown"

    def test_idle_when_no_patterns(self, monkeypatch):
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer",
            lambda: _FakeSynth([]),
        )
        out = DashboardAPIHandler._summarise_learning()
        assert out["active_patterns"] == 0
        assert out["status"] == "idle"

    def test_learning_when_patterns_but_none_firing(self, monkeypatch):
        rows = [
            {"signature": "error:x", "rule_id": "learned::error:x",
             "kind": "error", "sample_text": "m", "occurrences": 3,
             "first_seen": 0.0, "last_seen": 1.0, "confidence": 0.8},
        ]
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer",
            lambda: _FakeSynth(rows),
        )

        class _EmptyStore:
            def list_rules(self, tier=None):
                return [object()]
            def get_all_rule_stats(self):
                return []  # no matches
            def read_audit(self, limit=500):
                return []

        monkeypatch.setattr(
            "engines.meta_governance.policy_store.get_default_store",
            lambda: _EmptyStore(),
        )
        out = DashboardAPIHandler._summarise_learning()
        assert out["active_patterns"] == 1
        assert out["status"] == "learning"

    def test_healthy_when_patterns_are_firing(self, monkeypatch):
        rows = [
            {"signature": "error:x", "rule_id": "learned::error:x",
             "kind": "error", "sample_text": "m", "occurrences": 3,
             "first_seen": 0.0, "last_seen": 1.0, "confidence": 0.8},
        ]
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer",
            lambda: _FakeSynth(rows),
        )

        class _FiringStore:
            def list_rules(self, tier=None):
                return [object()]
            def get_all_rule_stats(self):
                return [
                    {"rule_id": "learned::error:x",
                     "source": "learned", "matches": 5},
                ]
            def read_audit(self, limit=500):
                return []

        monkeypatch.setattr(
            "engines.meta_governance.policy_store.get_default_store",
            lambda: _FiringStore(),
        )
        out = DashboardAPIHandler._summarise_learning()
        assert out["status"] == "healthy"
        assert out["soft_rules"] == 1

    def test_belief_count_and_half_life_surfaced(self, monkeypatch):
        monkeypatch.setattr(
            "core.reflection.synthesizer.get_default_synthesizer",
            lambda: _FakeSynth([]),
        )

        class _BS:
            half_life_seconds = 3600.0
            def keys(self):
                return ["a", "b", "c"]

        monkeypatch.setattr(
            "core.mentality.get_default_belief_store", lambda: _BS(),
        )
        out = DashboardAPIHandler._summarise_learning()
        assert out["beliefs"] == 3
        assert out["half_life"] == 3600.0

