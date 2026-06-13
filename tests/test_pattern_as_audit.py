"""Tests for engines._pattern_as_audit (Wave 375-378)."""
from __future__ import annotations

from engines._pattern_as_audit import (
    PatternASReport,
    PatternASViolation,
    run_pattern_as_audit,
)


class TestRunPatternASAudit:

    def test_returns_report(self):
        r = run_pattern_as_audit()
        assert isinstance(r, PatternASReport)

    def test_live_passes(self):
        r = run_pattern_as_audit()
        assert not r.has_violations, r.violations

    def test_total_knobs_matches_pattern_t(self):
        from engines._pattern_t_audit import (
            build_autonomy_env_registry,
        )
        r_as = run_pattern_as_audit()
        # AS counts UNIQUE knob names, Pattern T counts the
        # registry size (may have duplicates if collisions
        # exist). On a clean branch they should match.
        t = build_autonomy_env_registry()
        assert r_as.total_knobs == t.total_knobs

    def test_unique_count_equals_total_on_clean_branch(self):
        r = run_pattern_as_audit()
        assert r.unique_knobs == r.total_knobs
        assert r.duplicate_knobs == []


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternASViolation(knob="X")
        assert v.domains == []
        assert v.reason == ""

    def test_with_domains(self):
        v = PatternASViolation(
            knob="SHOPAI_X",
            domains=["a", "b"],
            reason="collision",
        )
        assert v.domains == ["a", "b"]


class TestReportDataclass:

    def test_empty_clean(self):
        r = PatternASReport()
        assert not r.has_violations
        assert r.total_knobs == 0
        assert r.unique_knobs == 0
        assert r.duplicate_knobs == []
