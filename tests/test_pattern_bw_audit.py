"""Tests for engines._pattern_bw_audit (Wave 927)."""
from __future__ import annotations

from engines._pattern_bw_audit import (
    PatternBWReport,
    PatternBWViolation,
    run_pattern_bw_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bw_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_four_invariants_checked(self):
        r = run_pattern_bw_audit()
        assert len(r.invariants_checked) == 4


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBWReport().has_violations

    def test_with_violations(self):
        r = PatternBWReport()
        r.violations.append(PatternBWViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
