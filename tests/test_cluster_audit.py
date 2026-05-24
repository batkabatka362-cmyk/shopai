"""Tests for engines._cluster_audit (9th institutional gate)."""
from __future__ import annotations

from engines._cluster_audit import audit_clusters


class TestRealCodebase:

    def test_no_violations_on_current_codebase(self):
        """If this fails, the substrate has drifted -- fix
        before merging."""
        report = audit_clusters()
        assert not report.has_violations, (
            f"Cluster audit found violations: "
            f"{report.violations}"
        )

    def test_info_lines_present(self):
        report = audit_clusters()
        # At least one informational line about cluster count
        assert any(
            "cluster definitions present" in i
            for i in report.info
        )

    def test_risk_summary_in_info(self):
        report = audit_clusters()
        # Risk class breakdown logged
        assert any("writer risk:" in i for i in report.info)
