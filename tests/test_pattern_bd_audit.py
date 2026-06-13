"""Tests for engines._pattern_bd_audit (Wave 864)."""
from __future__ import annotations

from engines._pattern_bd_audit import (
    PatternBDReport,
    PatternBDViolation,
    _file_references,
    run_pattern_bd_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bd_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_five_invariants_checked(self):
        r = run_pattern_bd_audit()
        # 5 invariants per the module docstring
        assert len(r.invariants_checked) == 5


class TestFileReferences:

    def test_all_present(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text(
            "from y import a, b\n", encoding="utf-8",
        )
        assert _file_references(f, "a", "b")

    def test_missing(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text("a only\n", encoding="utf-8")
        assert not _file_references(f, "a", "b")


class TestSyntheticDrift:

    def test_synthetic_missing_clear_cli(self, tmp_path):
        # Build a tree where cli.py doesn't register the
        # cooldown-clear subparser.
        (tmp_path / "cli.py").write_text(
            "no clear cli here\n", encoding="utf-8",
        )
        (tmp_path / "core" / "automation").mkdir(parents=True)
        (
            tmp_path / "core" / "automation"
            / "autonomy_armed.py"
        ).write_text("force\n", encoding="utf-8")
        r = run_pattern_bd_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "cli_registers_cooldown_clear"
        ]
        assert bad

    def test_synthetic_missing_force_flag(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "autonomy-cooldown-clear\n"
            "ArmCooldownError\n",
            encoding="utf-8",
        )
        (tmp_path / "core" / "automation").mkdir(parents=True)
        (
            tmp_path / "core" / "automation"
            / "autonomy_armed.py"
        ).write_text("force\n", encoding="utf-8")
        r = run_pattern_bd_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "cli_arm_has_force_flag"
        ]
        assert bad

    def test_synthetic_missing_cooldown_error_handling(
        self, tmp_path,
    ):
        # CLI registers everything except references the
        # ArmCooldownError class -> handler is missing
        (tmp_path / "cli.py").write_text(
            "autonomy-cooldown-clear\n"
            "autonomy_arm_p.add_argument(\n"
            "--force\n",
            encoding="utf-8",
        )
        (tmp_path / "core" / "automation").mkdir(parents=True)
        (
            tmp_path / "core" / "automation"
            / "autonomy_armed.py"
        ).write_text("force\n", encoding="utf-8")
        r = run_pattern_bd_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "cli_arm_handles_cooldown_error"
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBDReport().has_violations

    def test_with_violations(self):
        r = PatternBDReport()
        r.violations.append(PatternBDViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
