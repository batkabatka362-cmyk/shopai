"""Tests for Phase 12.D unified autonomy substrate."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from core.automation.autonomy_status import (
    AutonomyStatusReport,
    DomainSummary,
    get_autonomy_status,
)
from engines._pattern_p_audit import (
    PatternPReport,
    PatternPViolation,
    run_pattern_p_audit,
)


# ─── autonomy_status ─────────────────────────────────────


def _stub_status(verdict, paused=False, applied=0):
    return SimpleNamespace(
        verdict=verdict,
        refund_paused=paused,  # support shape
        paused=paused,         # other shapes
        refund_applied_count=applied,
        applied_count=applied,
        refund_failure_ratio=0.0,
        health_failure_ratio=0.0,
        verdict_reasons=[f"{verdict} from stub"],
        next_action="stub action",
    )


class TestAutonomyStatusAggregation:

    def test_all_healthy_overall_healthy(self):
        with patch(
            "core.automation.autonomy_status."
            "_customer_support_summary",
            return_value=DomainSummary(
                name="customer_support",
                verdict="healthy",
                applied_count=5,
            ),
        ), patch(
            "core.automation.autonomy_status._marketing_summary",
            return_value=DomainSummary(
                name="marketing",
                verdict="healthy",
                applied_count=3,
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_fulfillment_summary",
            return_value=DomainSummary(
                name="fulfillment",
                verdict="healthy",
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_inventory_summary",
            return_value=DomainSummary(
                name="inventory",
                verdict="healthy",
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_discount_cleanup_summary",
            return_value=DomainSummary(
                name="discount_cleanup",
                verdict="healthy",
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_order_followup_summary",
            return_value=DomainSummary(
                name="order_followup",
                verdict="healthy",
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_product_seo_summary",
            return_value=DomainSummary(
                name="product_seo",
                verdict="healthy",
            ),
        ):
            report = get_autonomy_status()
        assert report.overall_verdict == "healthy"
        assert report.total_applied == 8

    def test_one_paused_propagates_to_overall(self):
        with patch(
            "core.automation.autonomy_status."
            "_customer_support_summary",
            return_value=DomainSummary(
                name="customer_support",
                verdict="paused",
                paused=True,
                next_action="resume me",
            ),
        ), patch(
            "core.automation.autonomy_status._marketing_summary",
            return_value=DomainSummary(
                name="marketing", verdict="healthy",
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_fulfillment_summary",
            return_value=DomainSummary(
                name="fulfillment", verdict="healthy",
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_inventory_summary",
            return_value=DomainSummary(
                name="inventory", verdict="healthy",
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_discount_cleanup_summary",
            return_value=DomainSummary(
                name="discount_cleanup", verdict="healthy",
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_order_followup_summary",
            return_value=DomainSummary(
                name="order_followup", verdict="healthy",
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_product_seo_summary",
            return_value=DomainSummary(
                name="product_seo", verdict="healthy",
            ),
        ):
            report = get_autonomy_status()
        assert report.overall_verdict == "paused"
        assert "customer_support" in report.paused_domains
        assert "customer_support" in report.overall_next_action

    def test_degraded_beats_quiet(self):
        with patch(
            "core.automation.autonomy_status."
            "_customer_support_summary",
            return_value=DomainSummary(
                name="customer_support", verdict="quiet",
            ),
        ), patch(
            "core.automation.autonomy_status._marketing_summary",
            return_value=DomainSummary(
                name="marketing", verdict="degraded",
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_fulfillment_summary",
            return_value=DomainSummary(
                name="fulfillment", verdict="quiet",
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_inventory_summary",
            return_value=DomainSummary(
                name="inventory", verdict="healthy",
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_discount_cleanup_summary",
            return_value=DomainSummary(
                name="discount_cleanup", verdict="quiet",
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_order_followup_summary",
            return_value=DomainSummary(
                name="order_followup", verdict="quiet",
            ),
        ), patch(
            "core.automation.autonomy_status."
            "_product_seo_summary",
            return_value=DomainSummary(
                name="product_seo", verdict="quiet",
            ),
        ):
            report = get_autonomy_status()
        assert report.overall_verdict == "degraded"


# ─── pattern_p_audit ─────────────────────────────────────


class TestPatternPLive:
    """Pattern P passes on the current codebase."""

    def test_audit_finds_no_violations(self):
        report = run_pattern_p_audit()
        assert isinstance(report, PatternPReport)
        assert report.has_violations is False, (
            f"Pattern P regression: "
            f"{[(v.domain, v.file) for v in report.violations]}"
        )

    def test_scans_known_template_domains(self):
        report = run_pattern_p_audit()
        domains = set(report.scanned_domains)
        # The two domains built on top of core/automation/*
        assert "fulfillment_autonomy" in domains
        assert "inventory_autonomy" in domains
        # The grandfathered domains should NOT be in scanned
        assert "returns_management" not in domains
        assert "roas_guardrails" not in domains


class TestPatternPViolationDataclass:

    def test_report_has_violations(self):
        r = PatternPReport()
        assert r.has_violations is False
        r.violations.append(PatternPViolation(
            domain="foo", file="foo/_log.py",
            missing_import="core.automation.action_log",
        ))
        assert r.has_violations is True
