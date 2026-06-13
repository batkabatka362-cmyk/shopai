"""Tests for engines._pattern_bv_audit (Wave 918)."""
from __future__ import annotations

from engines._pattern_bv_audit import (
    PatternBVReport,
    PatternBVViolation,
    _WIREUP_ROSTER,
    run_pattern_bv_audit,
)


class TestRoster:

    def test_six_entries(self):
        # loyalty + 5 pending = 6 minters in the wireup roster
        assert len(_WIREUP_ROSTER) == 6

    def test_loyalty_is_first(self):
        assert _WIREUP_ROSTER[0][0] == "loyalty"


class TestLive:

    def test_strict_default_passes(self):
        # After Phase 175 closure: 6/6 wired, strict-default
        r = run_pattern_bv_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_all_wired(self):
        r = run_pattern_bv_audit()
        assert r.wired_count == 6
        assert r.pending_count == 0

    def test_non_strict_passes_too(self):
        # Loose mode still works for ergonomic progress queries
        r = run_pattern_bv_audit(strict=False)
        assert not r.has_violations


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBVReport().has_violations

    def test_with_violations(self):
        r = PatternBVReport()
        r.violations.append(PatternBVViolation(
            invariant="x", reason="y", engine="loyalty",
        ))
        assert r.has_violations
