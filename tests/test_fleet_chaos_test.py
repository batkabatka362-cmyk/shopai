"""Tests for engines.fleet_chaos_test — W963-34."""
from __future__ import annotations

from engines.fleet_chaos_test import FleetChaosTestEngine
from engines.fleet_chaos_test.runner import (
    _is_pattern_q,
    available_suites,
    run_chaos_tests,
)


# ── _is_pattern_q helper ──────────────────────────────────


class TestIsPatternQ:
    def test_valid_envelope(self):
        ok, _ = _is_pattern_q({
            "status": "success", "data": {},
            "meta": {}, "error": None,
        })
        assert ok

    def test_missing_key(self):
        ok, detail = _is_pattern_q({
            "status": "success", "data": {}, "meta": {},
        })
        assert not ok
        assert "error" in detail

    def test_bad_status(self):
        ok, _ = _is_pattern_q({
            "status": "weird", "data": {},
            "meta": {}, "error": None,
        })
        assert not ok

    def test_non_dict(self):
        ok, _ = _is_pattern_q("string")
        assert not ok


# ── run_chaos_tests ──────────────────────────────────────


class TestRunChaosTests:
    def test_runs_all_suites_by_default(self):
        r = run_chaos_tests()
        # All 3 suites; total = 10 tests
        assert r.total >= 5
        assert len(r.results) == r.total

    def test_filter_to_single_suite(self):
        r = run_chaos_tests(suite_filter="observation")
        suites = {res.suite for res in r.results}
        assert suites == {"observation"}

    def test_unknown_suite_returns_empty(self):
        r = run_chaos_tests(suite_filter="xyz")
        assert r.total == 0

    def test_empire_is_resilient(self):
        # After W963-34 fixes, all chaos tests should pass.
        r = run_chaos_tests()
        assert r.failed == 0, (
            f"Empire not resilient: {r.failed} chaos tests "
            "fail. Run: shopai chaos-test"
        )


# ── available_suites ─────────────────────────────────────


class TestAvailableSuites:
    def test_returns_known_suites(self):
        out = available_suites()
        assert "observation" in out
        assert "autopilot" in out
        assert "cross_store" in out


# ── Engine envelope ──────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = FleetChaosTestEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = FleetChaosTestEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = FleetChaosTestEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = FleetChaosTestEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = FleetChaosTestEngine().run({})
        assert r["meta"]["engine"] == "fleet_chaos_test"


class TestEngineActions:
    def test_resilient_verdict_when_all_pass(self):
        r = FleetChaosTestEngine().run({})
        assert r["data"]["verdict"] == "resilient"

    def test_suite_filter_threaded(self):
        r = FleetChaosTestEngine().run({
            "data": {"suite": "observation"},
        })
        suites = {
            x["suite"] for x in r["data"]["results"]
        }
        assert suites == {"observation"}

    def test_available_suites_listed(self):
        r = FleetChaosTestEngine().run({})
        assert (
            "observation" in r["data"]["available_suites"]
        )
