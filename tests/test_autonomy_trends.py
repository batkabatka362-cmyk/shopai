"""Tests for core.automation.autonomy_trends (Wave 606-612).

Trend analyzer that diffs activity counts across two adjacent
windows. Tests cover:
  - verdict classification (rising/falling/flat/new/dormant)
  - per-domain trend computation against the live (idle) branch
  - aggregate counters
  - one-line summary
"""
from __future__ import annotations

from core.automation.autonomy_trends import (
    DomainTrend,
    TrendReport,
    _classify_verdict,
    _RISING_THRESHOLD_PCT,
    _FALLING_THRESHOLD_PCT,
    run_autonomy_trends,
)


class TestClassifyVerdict:

    def test_both_zero_is_flat(self):
        verdict, pct = _classify_verdict(0, 0)
        assert verdict == "flat"
        assert pct == 0.0

    def test_cur_nonzero_prev_zero_is_new(self):
        verdict, pct = _classify_verdict(5, 0)
        assert verdict == "new"
        assert pct == 0.0

    def test_cur_zero_prev_nonzero_is_dormant(self):
        verdict, pct = _classify_verdict(0, 5)
        assert verdict == "dormant"
        assert pct == -100.0

    def test_50pct_increase_is_rising(self):
        verdict, pct = _classify_verdict(15, 10)
        assert verdict == "rising"
        assert pct == 50.0

    def test_50pct_decrease_is_falling(self):
        verdict, pct = _classify_verdict(5, 10)
        assert verdict == "falling"
        assert pct == -50.0

    def test_10pct_change_is_flat(self):
        # Below the 25% threshold
        verdict, pct = _classify_verdict(11, 10)
        assert verdict == "flat"
        assert pct == 10.0

    def test_threshold_exact_25pct_is_flat(self):
        # 25.0 is NOT > 25.0, so flat
        verdict, _ = _classify_verdict(125, 100)
        # 25.0% — at the threshold, flat
        assert verdict == "flat"

    def test_threshold_just_above_25pct_is_rising(self):
        verdict, _ = _classify_verdict(126, 100)
        assert verdict == "rising"

    def test_rising_threshold_constant(self):
        assert _RISING_THRESHOLD_PCT == 25.0

    def test_falling_threshold_constant(self):
        assert _FALLING_THRESHOLD_PCT == -25.0


class TestRunAutonomyTrends:

    def test_returns_report(self):
        r = run_autonomy_trends()
        assert isinstance(r, TrendReport)

    def test_covers_10_domains(self):
        r = run_autonomy_trends()
        assert len(r.domains) == 10

    def test_idle_branch_all_flat(self):
        # No autonomous fires recorded -> all 10 should be flat
        r = run_autonomy_trends()
        assert r.flat_count == 10
        assert r.rising_count == 0
        assert r.falling_count == 0
        assert r.new_count == 0
        assert r.dormant_count == 0
        for d in r.domains:
            assert d.verdict == "flat"

    def test_summary_quiet_when_all_flat(self):
        r = run_autonomy_trends()
        # All flat -> summary mentions "flat" (or "all quiet"
        # if zero domains; we have 9 so it's "9 flat")
        assert "flat" in r.overall_summary

    def test_window_hours_preserved(self):
        r = run_autonomy_trends(window_hours=48.0)
        assert r.window_hours == 48.0

    def test_per_domain_trend_shape(self):
        r = run_autonomy_trends()
        for d in r.domains:
            assert isinstance(d.domain, str)
            assert isinstance(d.current_total, int)
            assert isinstance(d.current_applied, int)
            assert isinstance(d.previous_total, int)
            assert isinstance(d.previous_applied, int)
            assert isinstance(d.delta_total, int)
            assert isinstance(d.delta_applied, int)
            assert isinstance(d.verdict, str)
            assert d.verdict in {
                "rising", "falling", "flat",
                "new", "dormant",
            }


class TestTrendReportAggregation:

    def test_empty_report_counts_zero(self):
        r = TrendReport(window_hours=24.0)
        assert r.rising_count == 0
        assert r.falling_count == 0
        assert r.flat_count == 0


class TestDomainTrendDataclass:

    def test_defaults(self):
        t = DomainTrend(domain="x")
        assert t.verdict == "flat"
        assert t.current_total == 0
        assert t.delta_pct == 0.0
