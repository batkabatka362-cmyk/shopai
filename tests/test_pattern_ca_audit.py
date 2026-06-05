"""Tests for Pattern CA -- Phase 4 substrate wiring audit (W963-67)."""
from __future__ import annotations

from unittest.mock import patch

from engines._pattern_ca_audit import (
    PatternCAViolation,
    _ast_parses,
    run_pattern_ca_audit,
)


class TestAstParses:
    def test_valid_source(self):
        assert _ast_parses("x = 1") is True

    def test_syntax_error(self):
        assert _ast_parses("def x(:") is False

    def test_empty_string(self):
        assert _ast_parses("") is True


class TestRunPatternCaAudit:
    def test_real_repo_is_clean(self):
        # The substrate IS wired right now -- so the live
        # run should report 0 violations.
        report = run_pattern_ca_audit()
        # If this fails, there's a real wiring regression on
        # branch.
        assert report.has_violations is False, (
            f"Pattern CA violations: "
            + ", ".join(
                f"[{v.surface}] {v.path}: {v.detail}"
                for v in report.violations
            )
        )
        # 8 canonical surfaces (7 from W963-67 + 1 from
        # W963-69 morning-brief diff wiring)
        assert report.probes_run == 8
        assert report.clean_probes == 8

    def test_missing_file_violates(self):
        with patch(
            "engines._pattern_ca_audit._read",
            return_value="",
        ):
            report = run_pattern_ca_audit()
        assert report.has_violations is True
        assert len(report.violations) == 8
        for v in report.violations:
            assert "missing" in v.detail.lower()

    def test_syntax_error_violates(self):
        with patch(
            "engines._pattern_ca_audit._read",
            return_value="def f(:",
        ):
            report = run_pattern_ca_audit()
        assert report.has_violations is True
        for v in report.violations:
            assert "syntaxerror" in v.detail.lower()

    def test_missing_needle_violates(self):
        # Source parses, but no Phase 4 references in it
        with patch(
            "engines._pattern_ca_audit._read",
            return_value="x = 1\n",
        ):
            report = run_pattern_ca_audit()
        assert report.has_violations is True
        for v in report.violations:
            assert "missing needles" in v.detail.lower()

    def test_violation_carries_surface_and_path(self):
        with patch(
            "engines._pattern_ca_audit._read",
            return_value="x = 1",
        ):
            report = run_pattern_ca_audit()
        for v in report.violations:
            assert isinstance(v, PatternCAViolation)
            assert v.surface
            assert v.path
