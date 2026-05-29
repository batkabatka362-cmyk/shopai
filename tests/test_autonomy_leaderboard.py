"""Tests for core.automation.autonomy_leaderboard (Wave 666+).

Per-domain activity / success-rate ranking. Tests cover:
  - sort modes (applied / success_rate / failure_ratio)
  - aggregate counters
  - per-entry shape + health/paused signal capture
"""
from __future__ import annotations

from core.automation.autonomy_leaderboard import (
    LeaderEntry,
    LeaderboardReport,
    _sort_key,
    run_autonomy_leaderboard,
)


class TestSortKey:

    def test_applied_sort_descending(self):
        a = LeaderEntry(domain="a", total=10, applied=8)
        b = LeaderEntry(domain="b", total=10, applied=3)
        assert _sort_key(a, "applied") < _sort_key(b, "applied")

    def test_failure_ratio_sort_descending(self):
        # high failure first
        a = LeaderEntry(
            domain="a", total=10, applied=2,
            failure_ratio=0.8,
        )
        b = LeaderEntry(
            domain="b", total=10, applied=9,
            failure_ratio=0.1,
        )
        assert _sort_key(a, "failure_ratio") < (
            _sort_key(b, "failure_ratio")
        )

    def test_success_rate_sort_descending(self):
        a = LeaderEntry(
            domain="a", total=10, applied=9,
            success_rate=0.9,
        )
        b = LeaderEntry(
            domain="b", total=10, applied=2,
            success_rate=0.2,
        )
        assert _sort_key(a, "success_rate") < (
            _sort_key(b, "success_rate")
        )


class TestRunAutonomyLeaderboard:

    def test_returns_report(self):
        r = run_autonomy_leaderboard()
        assert isinstance(r, LeaderboardReport)

    def test_covers_10_domains(self):
        r = run_autonomy_leaderboard()
        assert len(r.entries) == 10

    def test_default_sort_is_applied(self):
        r = run_autonomy_leaderboard()
        assert r.sort_by == "applied"

    def test_alternate_sort_preserved(self):
        r = run_autonomy_leaderboard(
            sort_by="failure_ratio",
        )
        assert r.sort_by == "failure_ratio"

    def test_idle_branch_aggregates_zero(self):
        # No autonomous fires recorded
        r = run_autonomy_leaderboard()
        assert r.total_applied_fleet == 0
        assert r.total_skipped_fleet == 0
        assert r.active_count == 0
        for e in r.entries:
            assert e.total == 0
            assert e.applied == 0
            assert e.success_rate == 0.0
            assert e.failure_ratio == 0.0

    def test_each_entry_has_health_verdict(self):
        r = run_autonomy_leaderboard()
        for e in r.entries:
            assert isinstance(e.health_verdict, str)
            # idle branch should have healthy or unknown
            assert e.health_verdict in {
                "healthy", "degraded", "critical", "unknown",
            }

    def test_window_hours_passed_through(self):
        r = run_autonomy_leaderboard(window_hours=24.0)
        assert r.window_hours == 24.0


class TestLeaderboardReportDataclass:

    def test_defaults(self):
        r = LeaderboardReport(window_hours=24.0)
        assert r.entries == []
        assert r.total_applied_fleet == 0
        assert r.sort_by == "applied"


class TestLeaderEntryDataclass:

    def test_defaults(self):
        e = LeaderEntry(domain="x")
        assert e.total == 0
        assert e.applied == 0
        assert not e.paused
        assert e.health_verdict == "unknown"
