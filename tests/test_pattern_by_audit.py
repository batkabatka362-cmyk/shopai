"""Tests for engines._pattern_by_audit (Wave 933)."""
from __future__ import annotations

from engines._pattern_by_audit import (
    PatternBYReport,
    PatternBYViolation,
    _EXPECTED_ENTRY_FIELDS,
    _WIREUP_ROSTER,
    run_pattern_by_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_by_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_invariant_count(self):
        # 4 substrate + 6 per-applier = 10
        r = run_pattern_by_audit()
        assert len(r.invariants_checked) == 10


class TestExpectedSchema:

    def test_entry_fields_complete(self):
        assert "blocked_at" in _EXPECTED_ENTRY_FIELDS
        assert "engine" in _EXPECTED_ENTRY_FIELDS
        assert "store_id" in _EXPECTED_ENTRY_FIELDS

    def test_roster_six_entries(self):
        assert len(_WIREUP_ROSTER) == 6


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBYReport().has_violations

    def test_with_violations(self):
        r = PatternBYReport()
        r.violations.append(PatternBYViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
