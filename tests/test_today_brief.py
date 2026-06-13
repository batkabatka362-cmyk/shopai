"""Tests for engines.today_brief — W963-18."""
from __future__ import annotations

from unittest.mock import patch

from engines.today_brief import TodayBriefEngine
from engines.today_brief.collector import (
    TodaySignal,
    collect_today_signals,
    first_critical_action,
    overall_verdict,
)


# ── overall_verdict ───────────────────────────────────────


class TestOverallVerdict:
    def test_all_ok(self):
        sigs = [
            TodaySignal(name="a", verdict="ok", headline="x"),
            TodaySignal(name="b", verdict="ok", headline="y"),
        ]
        assert overall_verdict(sigs) == "ok"

    def test_one_warn_dominates(self):
        sigs = [
            TodaySignal(name="a", verdict="ok", headline="x"),
            TodaySignal(name="b", verdict="warn", headline="y"),
        ]
        assert overall_verdict(sigs) == "warn"

    def test_critical_dominates_warn(self):
        sigs = [
            TodaySignal(name="a", verdict="warn", headline=""),
            TodaySignal(
                name="b", verdict="critical", headline="",
            ),
        ]
        assert overall_verdict(sigs) == "critical"

    def test_all_skipped(self):
        sigs = [
            TodaySignal(
                name="a", verdict="skipped", headline="",
            ),
        ]
        assert overall_verdict(sigs) == "skipped"


# ── first_critical_action ─────────────────────────────────


class TestFirstCriticalAction:
    def test_picks_critical_first(self):
        sigs = [
            TodaySignal(
                name="warmup_plan", verdict="ok",
                headline="", drill="plan-drill",
            ),
            TodaySignal(
                name="x", verdict="critical",
                headline="", drill="critical-drill",
            ),
        ]
        assert first_critical_action(sigs) == "critical-drill"

    def test_falls_back_to_warmup_plan(self):
        sigs = [
            TodaySignal(
                name="warmup_plan", verdict="ok",
                headline="", drill="plan-drill",
            ),
            TodaySignal(name="x", verdict="ok", headline=""),
        ]
        assert first_critical_action(sigs) == "plan-drill"

    def test_empty(self):
        assert first_critical_action([]) == ""


# ── Collector graceful-degrade ─────────────────────────────


class TestCollectorDegrades:
    def test_collector_returns_5_signals(self):
        sigs = collect_today_signals(
            day=1, niche="beauty", store_id=None,
        )
        assert len(sigs) == 5
        names = {s.name for s in sigs}
        assert names == {
            "warmup_plan", "readiness", "autonomy",
            "cycle", "approvals",
        }

    def test_day_31_marks_warmup_skipped(self):
        sigs = collect_today_signals(
            day=31, niche=None, store_id=None,
        )
        wp = [s for s in sigs if s.name == "warmup_plan"][0]
        assert wp.verdict == "skipped"


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_input_success(self):
        result = TodayBriefEngine().run({})
        assert result["status"] == "success"
        assert "signals" in result["data"]

    def test_none_input_success(self):
        result = TodayBriefEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_error(self):
        result = TodayBriefEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream(self):
        result = TodayBriefEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"

    def test_carries_engine_name(self):
        result = TodayBriefEngine().run({})
        assert result["meta"]["engine"] == "today_brief"


class TestEngineActions:
    def test_day_clamped(self):
        result = TodayBriefEngine().run({
            "data": {"day": 999},
        })
        assert result["data"]["day"] == 30

    def test_day_negative_clamped(self):
        result = TodayBriefEngine().run({
            "data": {"day": -5},
        })
        assert result["data"]["day"] == 1

    def test_day_non_int_defaults_to_1(self):
        result = TodayBriefEngine().run({
            "data": {"day": "abc"},
        })
        assert result["data"]["day"] == 1

    def test_niche_lowercased(self):
        result = TodayBriefEngine().run({
            "data": {"niche": "BEAUTY"},
        })
        assert result["data"]["niche"] == "beauty"

    def test_store_id_threaded(self):
        result = TodayBriefEngine().run({
            "data": {"store_id": "main"},
        })
        assert result["data"]["store_id"] == "main"

    def test_signals_carry_verdict_field(self):
        result = TodayBriefEngine().run({})
        for s in result["data"]["signals"]:
            assert s["verdict"] in {
                "ok", "warn", "critical", "skipped",
            }

    def test_overall_verdict_present(self):
        result = TodayBriefEngine().run({})
        assert result["data"]["verdict"] in {
            "ok", "warn", "critical", "skipped",
        }

    def test_warmup_collector_isolated_per_signal(self):
        # Each collector has internal try/except so failure in
        # one substrate doesn't kill the brief.
        sigs = collect_today_signals(
            day=99, niche=None, store_id=None,
        )
        # day=99 is out-of-range -> warmup signal verdict
        # "skipped" rather than crash.
        wp = [s for s in sigs if s.name == "warmup_plan"][0]
        assert wp.verdict == "skipped"
        # Other signals still run normally.
        names = {s.name for s in sigs}
        assert "readiness" in names
