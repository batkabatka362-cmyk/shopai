"""Tests for engines._pattern_u_audit + _pattern_v_audit
(Waves 203, 207)."""
from __future__ import annotations

from engines._pattern_u_audit import (
    PatternUReport,
    PatternUViolation,
    _DOMAIN_BRIDGES,
    run_pattern_u_audit,
)
from engines._pattern_v_audit import (
    PatternVReport,
    PatternVViolation,
    _DOMAIN_ALERT_KINDS,
    run_pattern_v_audit,
)


# ─── Pattern U ───────────────────────────────────────────


class TestPatternULive:

    def test_audit_passes_on_current_codebase(self):
        report = run_pattern_u_audit()
        assert isinstance(report, PatternUReport)
        assert report.has_violations is False

    def test_scans_all_domains(self):
        # W937: roster grew over time; subset semantics
        report = run_pattern_u_audit()
        assert len(report.domains_scanned) >= 7
        assert len(report.domains_scanned) == len(
            _DOMAIN_BRIDGES,
        )

    def test_all_known_bridges_referenced(self):
        report = run_pattern_u_audit()
        for domain in _DOMAIN_BRIDGES:
            assert domain in report.clean_domains


class TestPatternUMissingCliPath:

    def test_missing_cli_path_flags_every_domain(
        self, tmp_path,
    ):
        fake_path = tmp_path / "no_such_cli.py"
        report = run_pattern_u_audit(cli_path=fake_path)
        # All known domains flagged (count grows with the
        # roster).
        assert report.has_violations
        assert len(report.violations) == len(_DOMAIN_BRIDGES)


class TestPatternUViolation:

    def test_default(self):
        v = PatternUViolation(
            domain="x", bridge_name="maybe_x",
        )
        assert v.reason == ""


# ─── Pattern V ───────────────────────────────────────────


class TestPatternVLive:

    def test_audit_passes_on_current_codebase(self):
        report = run_pattern_v_audit()
        assert isinstance(report, PatternVReport)
        assert report.has_violations is False

    def test_scans_all_domains(self):
        # W937: roster grew; subset semantics
        report = run_pattern_v_audit()
        assert len(report.domains_scanned) >= 7
        assert len(report.domains_scanned) == len(
            _DOMAIN_ALERT_KINDS,
        )

    def test_alert_kinds_canonical(self):
        # Each domain has exactly 2 alert kinds
        for domain, kinds in _DOMAIN_ALERT_KINDS.items():
            assert len(kinds) == 2
            # Standard suffixes
            assert any(k.endswith("_paused") for k in kinds)
            assert any(
                k.endswith("_health_critical") for k in kinds
            )


class TestPatternVMissingNotifyPath:

    def test_missing_notify_path_flags_every_domain(
        self, tmp_path,
    ):
        fake_path = tmp_path / "no_such_notify.py"
        report = run_pattern_v_audit(notify_path=fake_path)
        # W937: roster grew; subset semantics
        assert report.has_violations
        assert len(report.violations) == len(
            _DOMAIN_ALERT_KINDS,
        )


class TestPatternVViolation:

    def test_default(self):
        v = PatternVViolation(domain="x")
        assert v.missing_kinds == []
        assert v.reason == ""
