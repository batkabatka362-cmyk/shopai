"""Tests for engines._pattern_r_audit (Wave 164)."""
from __future__ import annotations

from engines._pattern_r_audit import (
    PatternRReport,
    PatternRViolation,
    run_pattern_r_audit,
)


class TestPatternRLive:

    def test_audit_passes_on_current_codebase(self):
        report = run_pattern_r_audit()
        assert isinstance(report, PatternRReport)
        assert report.has_violations is False

    def test_probes_all_6_domains(self):
        report = run_pattern_r_audit()
        assert set(report.domains_probed) == {
            "customer_support", "marketing",
            "fulfillment", "inventory",
            "discount_cleanup", "order_followup",
        }


class TestPatternRViolation:

    def test_default(self):
        v = PatternRViolation(domain="foo")
        assert v.reason == ""

    def test_report_has_violations(self):
        r = PatternRReport()
        assert r.has_violations is False
        r.violations.append(PatternRViolation(domain="x"))
        assert r.has_violations is True
