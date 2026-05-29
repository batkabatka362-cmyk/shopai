"""Tests for engines._pattern_aq_audit (Wave 358-362)."""
from __future__ import annotations

from engines._pattern_aq_audit import (
    CANONICAL_VERDICTS,
    PatternAQReport,
    PatternAQViolation,
    run_pattern_aq_audit,
)


class TestCanonicalSet:

    def test_canonical_verdicts_is_4(self):
        assert len(CANONICAL_VERDICTS) == 4

    def test_canonical_verdicts_match_severity_set(self):
        # The audit's canonical set should mirror exactly what
        # autonomy_status._VERDICT_SEVERITY accepts.
        from core.automation.autonomy_status import (
            _VERDICT_SEVERITY,
        )
        assert CANONICAL_VERDICTS == set(
            _VERDICT_SEVERITY.keys(),
        )

    def test_canonical_includes_expected_literals(self):
        assert "healthy" in CANONICAL_VERDICTS
        assert "quiet" in CANONICAL_VERDICTS
        assert "degraded" in CANONICAL_VERDICTS
        assert "paused" in CANONICAL_VERDICTS


class TestRunPatternAQAudit:

    def test_returns_report(self):
        r = run_pattern_aq_audit()
        assert isinstance(r, PatternAQReport)

    def test_scans_all_10_domains(self):
        r = run_pattern_aq_audit()
        assert len(r.domains_scanned) == 10

    def test_live_passes(self):
        r = run_pattern_aq_audit()
        assert not r.has_violations, r.violations
        assert len(r.clean_domains) == 10

    def test_verdicts_by_domain_populated(self):
        r = run_pattern_aq_audit()
        assert len(r.verdicts_by_domain) == 10
        for d, verdict in r.verdicts_by_domain.items():
            assert verdict in CANONICAL_VERDICTS, (
                d, verdict,
            )


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternAQViolation(domain="x")
        assert v.actual_verdict == ""
        assert v.reason == ""

    def test_with_actual_verdict(self):
        v = PatternAQViolation(
            domain="x",
            actual_verdict="broken",
            reason="not canonical",
        )
        assert v.actual_verdict == "broken"


class TestReportDataclass:

    def test_empty_clean(self):
        r = PatternAQReport()
        assert not r.has_violations
        assert r.verdicts_by_domain == {}
