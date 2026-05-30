"""Tests for engines._pattern_bu_audit (Wave 916)."""
from __future__ import annotations

from engines._pattern_bu_audit import (
    PatternBUReport,
    PatternBUViolation,
    run_pattern_bu_audit,
)


class TestLive:

    def test_live_branch_passes(self, monkeypatch):
        # Force the env var unset so invariant 1's "off"
        # branch can validate
        monkeypatch.delenv("SHOPAI_THRASH_GUARDRAIL", False)
        r = run_pattern_bu_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_four_invariants_checked(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_THRASH_GUARDRAIL", False)
        r = run_pattern_bu_audit()
        assert len(r.invariants_checked) == 4


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBUReport().has_violations

    def test_with_violations(self):
        r = PatternBUReport()
        r.violations.append(PatternBUViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
