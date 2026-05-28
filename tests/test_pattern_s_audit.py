"""Tests for engines._pattern_s_audit (Wave 181)."""
from __future__ import annotations

from engines._pattern_s_audit import (
    PatternSReport,
    PatternSViolation,
    _is_autonomy_command,
    run_pattern_s_audit,
)


class TestIsAutonomyCommand:

    def test_known_autonomy_status_match(self):
        for cmd in (
            "refund-status",
            "marketing-status",
            "fulfillment-status",
            "inventory-status",
            "discount-cleanup-status",
            "order-followup-status",
        ):
            assert _is_autonomy_command(cmd), (
                f"{cmd} should match"
            )

    def test_health_pause_resume_match(self):
        for cmd in (
            "refund-health",
            "marketing-pause",
            "fulfillment-resume",
        ):
            assert _is_autonomy_command(cmd)

    def test_non_autonomy_rejected(self):
        for cmd in (
            "store-add",
            "cycle-status",
            "engine-pulse",
            "approvals-show",
        ):
            assert not _is_autonomy_command(cmd), (
                f"{cmd} should NOT match"
            )


class TestPatternSLive:

    def test_audit_passes_on_current_codebase(self):
        report = run_pattern_s_audit()
        assert isinstance(report, PatternSReport)
        assert report.has_violations is False, (
            f"Pattern S regression: "
            f"{[(v.command, v.reason) for v in report.violations]}"
        )

    def test_scans_all_known_autonomy_commands(self):
        """The audit should find all 24+ autonomy commands
        across 6 domains x 4 verbs + autonomy-status +
        support-status."""
        report = run_pattern_s_audit()
        # At minimum: 6 domains × 4 verbs = 24 commands
        # Plus autonomy-status + support-status (refund-*
        # variant)
        assert len(report.commands_scanned) >= 24

    def test_known_commands_in_scanned_set(self):
        report = run_pattern_s_audit()
        scanned = set(report.commands_scanned)
        for expected in (
            "refund-status",
            "marketing-health",
            "fulfillment-pause",
            "inventory-resume",
            "discount-cleanup-status",
            "order-followup-health",
            "autonomy-status",
        ):
            assert expected in scanned


class TestPatternSViolationDataclass:

    def test_default(self):
        v = PatternSViolation(command="foo")
        assert v.reason == ""

    def test_has_violations(self):
        r = PatternSReport()
        assert r.has_violations is False
        r.violations.append(PatternSViolation(command="x"))
        assert r.has_violations is True
