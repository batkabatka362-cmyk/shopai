"""Tests for engines.cron_recommender — W963-59."""
from __future__ import annotations

from unittest.mock import patch

from engines.cron_recommender import CronRecommenderEngine
from engines.cron_recommender.recommender import (
    _decide,
    _windows_template,
    platform_template,
    recommend,
)


# ── _decide ───────────────────────────────────────────────


class TestDecide:
    def test_empty_empire(self):
        interval, reason, conf = _decide({})
        assert interval == 1.0
        assert "Empty empire" in reason
        assert conf == "low"

    def test_critical_anomaly_overrides(self):
        interval, reason, conf = _decide({
            "cycles_7d": 100,
            "cycles_per_day": 14.0,
            "actions_per_cycle": 3.0,
            "critical_anomaly_count": 2,
        })
        assert interval == 1.0
        assert "critical anomaly" in reason
        assert conf == "high"

    def test_high_failure_rate(self):
        interval, reason, conf = _decide({
            "cycles_7d": 14,
            "cycles_per_day": 2.0,
            "cycles_failure_rate": 0.4,
        })
        assert interval == 2.0
        assert "failure rate" in reason
        assert conf == "medium"

    def test_high_drift(self):
        interval, reason, conf = _decide({
            "cycles_7d": 50,
            "cycles_per_day": 7.0,
            "cycles_failure_rate": 0.0,
            "verdict_drift_per_day": 3.5,
        })
        assert interval == 1.0
        assert "shifting" in reason

    def test_waste_reduce(self):
        interval, reason, conf = _decide({
            "cycles_7d": 100,
            "cycles_per_day": 14.0,
            "cycles_failure_rate": 0.0,
            "verdict_drift_per_day": 0.1,
            "actions_per_cycle": 0.1,
        })
        assert interval == 4.0
        assert "actions each" in reason
        assert conf == "high"

    def test_very_low_activity_daily(self):
        interval, reason, conf = _decide({
            "cycles_7d": 7,
            "cycles_per_day": 1.0,
            "cycles_failure_rate": 0.0,
            "verdict_drift_per_day": 0.1,
            "actions_per_cycle": 0.2,
        })
        assert interval == 24.0
        assert "Very low activity" in reason

    def test_steady_state_default(self):
        interval, reason, conf = _decide({
            "cycles_7d": 14,
            "cycles_per_day": 2.0,
            "cycles_failure_rate": 0.0,
            "verdict_drift_per_day": 1.0,
            "actions_per_cycle": 2.5,
        })
        assert interval == 2.0
        assert "Steady-state" in reason


# ── _windows_template ─────────────────────────────────────


class TestWindowsTemplate:
    def test_hourly(self):
        out = _windows_template(1.0)
        assert "HOURLY" in out
        assert "/MO" not in out

    def test_multi_hour(self):
        out = _windows_template(2.0)
        assert "HOURLY /MO 2" in out

    def test_daily(self):
        out = _windows_template(48.0)
        assert "DAILY" in out


# ── platform_template ─────────────────────────────────────


class TestPlatformTemplate:
    def test_picks_template(self):
        # Sentinel test: at least returns a non-empty string
        rec = recommend(signals_override={})
        assert platform_template(rec) != ""


# ── recommend() ───────────────────────────────────────────


class TestRecommend:
    def test_empty_returns_hourly(self):
        rec = recommend(signals_override={})
        assert rec.interval_hours == 1.0
        assert "Empty" in rec.reason

    def test_signals_pass_through(self):
        rec = recommend(signals_override={
            "cycles_7d": 50, "critical_anomaly_count": 1,
        })
        assert rec.signals.get("cycles_7d") == 50
        assert rec.interval_hours == 1.0

    def test_cron_line_present(self):
        rec = recommend(signals_override={})
        assert rec.cron_line
        assert "shopai cycle" in rec.cron_line

    def test_windows_task_present(self):
        rec = recommend(signals_override={})
        assert rec.windows_task

    def test_known_interval_uses_canned_cron(self):
        rec = recommend(signals_override={})
        # hourly should map to "0 * * * *"
        assert "0 * * * *" in rec.cron_line


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = CronRecommenderEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = CronRecommenderEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = CronRecommenderEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = CronRecommenderEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = CronRecommenderEngine().run({})
        assert (
            r["meta"]["engine"] == "cron_recommender"
        )

    def test_data_has_all_required_keys(self):
        r = CronRecommenderEngine().run({})
        for key in (
            "interval_hours", "reason", "cron_line",
            "windows_task", "confidence", "signals",
            "platform_template", "next_action",
        ):
            assert key in r["data"]
