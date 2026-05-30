"""Tests for engines._pattern_bp_audit (Wave 899)."""
from __future__ import annotations

from engines._pattern_bp_audit import (
    PatternBPReport,
    PatternBPViolation,
    run_pattern_bp_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bp_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_five_invariants_checked(self):
        r = run_pattern_bp_audit()
        assert len(r.invariants_checked) == 5


class TestSyntheticDrift:

    def test_synthetic_missing_markdown_flag(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "autonomy_overview_p.add_argument(\n"
            '    "--shell-prompt", action="store_true",\n'
            ")\n",
            encoding="utf-8",
        )
        r = run_pattern_bp_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "cli_registers_markdown_flag"
        ]
        assert bad

    def test_synthetic_missing_shell_prompt_flag(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "autonomy_overview_p.add_argument(\n"
            '    "--markdown", action="store_true",\n'
            ")\n",
            encoding="utf-8",
        )
        r = run_pattern_bp_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == (
                "cli_registers_shell_prompt_flag"
            )
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBPReport().has_violations

    def test_with_violations(self):
        r = PatternBPReport()
        r.violations.append(PatternBPViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
