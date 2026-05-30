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

    def test_non_strict_passes(self):
        # Loose mode: missing wireups don't fail the audit
        r = run_pattern_bv_audit(strict=False)
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_loyalty_is_wired(self):
        r = run_pattern_bv_audit(strict=False)
        assert r.wired_count >= 1

    def test_pending_counted(self):
        r = run_pattern_bv_audit(strict=False)
        # 6 minters - 1 wired = 5 pending
        assert r.pending_count == 5

    def test_strict_mode_fails_on_pending(self):
        r = run_pattern_bv_audit(strict=True)
        assert r.has_violations
        # Each pending counts as 1 violation
        assert len(r.violations) >= 5


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBVReport().has_violations

    def test_with_violations(self):
        r = PatternBVReport()
        r.violations.append(PatternBVViolation(
            invariant="x", reason="y", engine="loyalty",
        ))
        assert r.has_violations
