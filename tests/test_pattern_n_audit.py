"""Tests for engines._pattern_n_audit (Wave 121)."""
from __future__ import annotations

from engines._pattern_n_audit import (
    PatternNReport,
    PatternNViolation,
    _BEAUTY_TOP_CLUSTERS,
    run_pattern_n_audit,
)


class TestPatternNAuditLive:
    """The audit must pass on the current codebase -- Wave 89
    fixed AIOrchestratorStrategy + Wave 73 wired the
    deterministic + revenue-aware paths."""

    def test_audit_finds_no_violations(self):
        report = run_pattern_n_audit()
        assert isinstance(report, PatternNReport)
        assert report.has_violations is False, (
            f"Pattern N regression: {report.violations}"
        )

    def test_real_strategies_probed(self):
        report = run_pattern_n_audit()
        # All three real strategies in our codebase
        assert "DeterministicOrchestratorStrategy" in (
            report.strategies_probed
        )
        assert "AIOrchestratorStrategy" in (
            report.strategies_probed
        )
        assert "RevenueAwareOrchestratorStrategy" in (
            report.strategies_probed
        )


class TestBeautyClusterSet:

    def test_beauty_clusters_match_niche_priority(self):
        """The probe checks for beauty's top-3 clusters from
        Wave 73's niche priority. Sync those here so a future
        rename of the niche-priority list won't silently break
        the audit's assertion."""
        from engines._niche_priority import niche_cluster_focus
        focus = niche_cluster_focus("beauty")
        # _BEAUTY_TOP_CLUSTERS should be a subset of beauty's
        # top entries
        for cluster in _BEAUTY_TOP_CLUSTERS:
            assert cluster in focus, (
                f"_BEAUTY_TOP_CLUSTERS includes '{cluster}' "
                f"but niche_priority.beauty = {focus}"
            )


class TestViolationDataclass:

    def test_violation_default_fields(self):
        v = PatternNViolation(strategy_class="Test")
        assert v.cluster_focus == []
        assert v.reason == ""

    def test_report_has_violations_property(self):
        r = PatternNReport()
        assert r.has_violations is False
        r.violations.append(PatternNViolation(
            strategy_class="X", reason="...",
        ))
        assert r.has_violations is True
