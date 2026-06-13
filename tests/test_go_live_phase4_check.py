"""Tests for go-live Phase 4 substrate check (W963-61)."""
from __future__ import annotations

from unittest.mock import patch

from engines._go_live_check import (
    _check_phase4_substrate,
    run_go_live_check,
)


class TestPhase4Check:
    def test_pass_when_fresh_snapshots(self):
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
        ), patch(
            "engines.agi_anomaly_detector.detector.detect",
        ), patch(
            "engines.cron_recommender.recommender.recommend",
        ), patch(
            "engines.agi_earnings_history.store."
            "snapshot_count",
            return_value=10,
        ), patch(
            "engines.agi_earnings_history.store.latest",
        ) as fake_latest:
            import time
            fake_latest.return_value = {
                "ts": time.time() - 3600,
                "verdict": "earning",
            }
            r = _check_phase4_substrate()
        assert r.status == "pass"
        assert "10 snapshot" in r.detail

    def test_warn_when_zero_snapshots(self):
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
        ), patch(
            "engines.agi_anomaly_detector.detector.detect",
        ), patch(
            "engines.cron_recommender.recommender.recommend",
        ), patch(
            "engines.agi_earnings_history.store."
            "snapshot_count",
            return_value=0,
        ):
            r = _check_phase4_substrate()
        assert r.status == "warn"
        assert "0 history snapshots" in r.detail
        assert "morning-brief --record" in r.fix

    def test_warn_when_snapshots_stale(self):
        import time
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
        ), patch(
            "engines.agi_anomaly_detector.detector.detect",
        ), patch(
            "engines.cron_recommender.recommender.recommend",
        ), patch(
            "engines.agi_earnings_history.store."
            "snapshot_count",
            return_value=5,
        ), patch(
            "engines.agi_earnings_history.store.latest",
            return_value={
                "ts": time.time() - (72 * 3600),
                "verdict": "earning",
            },
        ):
            r = _check_phase4_substrate()
        assert r.status == "warn"
        assert "> 48h old" in r.detail

    def test_fail_when_summary_raises(self):
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
            side_effect=RuntimeError("boom"),
        ), patch(
            "engines.agi_anomaly_detector.detector.detect",
        ), patch(
            "engines.cron_recommender.recommender.recommend",
        ):
            r = _check_phase4_substrate()
        assert r.status == "fail"
        assert "summary" in r.detail

    def test_fail_when_anomaly_raises(self):
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
        ), patch(
            "engines.agi_anomaly_detector.detector.detect",
            side_effect=RuntimeError("x"),
        ), patch(
            "engines.cron_recommender.recommender.recommend",
        ):
            r = _check_phase4_substrate()
        assert r.status == "fail"
        assert "anomaly" in r.detail

    def test_fail_when_recommender_raises(self):
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
        ), patch(
            "engines.agi_anomaly_detector.detector.detect",
        ), patch(
            "engines.cron_recommender.recommender.recommend",
            side_effect=RuntimeError("x"),
        ):
            r = _check_phase4_substrate()
        assert r.status == "fail"
        assert "cron" in r.detail

    def test_multiple_failures_all_listed(self):
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
            side_effect=RuntimeError("a"),
        ), patch(
            "engines.agi_anomaly_detector.detector.detect",
            side_effect=RuntimeError("b"),
        ), patch(
            "engines.cron_recommender.recommender.recommend",
        ):
            r = _check_phase4_substrate()
        assert r.status == "fail"
        assert "summary" in r.detail
        assert "anomaly" in r.detail


class TestRunGoLiveCheck:
    def test_phase4_check_in_roster(self):
        results = run_go_live_check()
        names = [r.name for r in results]
        assert "phase4_substrate" in names

    def test_check_order_phase4_last(self):
        results = run_go_live_check()
        names = [r.name for r in results]
        # phase4 is appended after revenue_readiness
        assert names[-1] == "phase4_substrate"
