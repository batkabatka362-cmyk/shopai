"""Tests for engines._pattern_r_audit (Wave 164)."""
from __future__ import annotations

from unittest.mock import patch

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

    def test_probes_all_10_domains(self):
        """W937 bugfix: probe expanded from 7 to 10 domains
        (customer_outreach W379, catalog_quality W436,
        shipping_alert W756 were silently skipped)."""
        report = run_pattern_r_audit()
        assert set(report.domains_probed) == {
            "customer_support", "marketing",
            "fulfillment", "inventory",
            "discount_cleanup", "order_followup",
            "product_seo", "customer_outreach",
            "catalog_quality", "shipping_alert",
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


class TestPatternRScanPath:
    """W937 bugfix #9: real synthetic-failure tests that
    actually exercise the audit's violation-detection code
    path. Pre-fix tests only verified dataclass append, never
    the scan."""

    def test_empty_next_action_triggers_violation(self):
        """Mock the customer_support summary to return an
        empty next_action -- audit must flag it."""
        from types import SimpleNamespace
        broken = lambda **kw: SimpleNamespace(
            next_action="", verdict="quiet",
        )
        with patch(
            "core.automation.autonomy_status."
            "_customer_support_summary",
            broken,
        ):
            r = run_pattern_r_audit()
        assert r.has_violations
        flagged = [
            v for v in r.violations
            if v.domain == "customer_support"
            and "empty" in v.reason
        ]
        assert flagged, (
            "audit did not flag empty next_action on "
            "customer_support"
        )

    def test_whitespace_next_action_triggers_violation(self):
        """All-whitespace next_action should also flag --
        prevents 'fix' by inserting '   ' to dodge audit."""
        from types import SimpleNamespace
        broken = lambda **kw: SimpleNamespace(
            next_action="   ", verdict="quiet",
        )
        with patch(
            "core.automation.autonomy_status."
            "_marketing_summary",
            broken,
        ):
            r = run_pattern_r_audit()
        assert any(
            v.domain == "marketing" for v in r.violations
        )

    def test_summary_raise_triggers_violation(self):
        """If a summary function raises, the audit must catch
        and report instead of bubbling the exception up."""
        def broken(**kw):
            raise RuntimeError("summary broke")
        with patch(
            "core.automation.autonomy_status."
            "_fulfillment_summary",
            broken,
        ):
            r = run_pattern_r_audit()
        flagged = [
            v for v in r.violations
            if v.domain == "fulfillment" and "raised" in v.reason
        ]
        assert flagged
