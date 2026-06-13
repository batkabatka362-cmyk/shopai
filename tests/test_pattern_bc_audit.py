"""Tests for engines._pattern_bc_audit (Wave 861)."""
from __future__ import annotations

from engines._pattern_bc_audit import (
    PatternBCReport,
    PatternBCViolation,
    _file_references,
    run_pattern_bc_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bc_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_six_invariants_checked(self):
        r = run_pattern_bc_audit()
        # 6 invariants per the module docstring
        assert len(r.invariants_checked) == 6


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

    def test_synthetic_broken_auto_disarm(self, tmp_path):
        # Build a tree where substrate_fire_auto_disarm.py
        # doesn't reference record_disarm_decisions -> Pattern
        # BC should flag.
        (tmp_path / "core" / "automation").mkdir(parents=True)
        (
            tmp_path / "core" / "automation"
            / "substrate_fire_auto_disarm.py"
        ).write_text("# empty\n", encoding="utf-8")
        (
            tmp_path / "core" / "automation"
            / "autonomy_armed.py"
        ).write_text(
            "from x import last_disarm_at\n",
            encoding="utf-8",
        )
        r = run_pattern_bc_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "auto_disarm_records_decisions"
        ]
        assert bad

    def test_synthetic_broken_arm_reader(self, tmp_path):
        (tmp_path / "core" / "automation").mkdir(parents=True)
        (
            tmp_path / "core" / "automation"
            / "substrate_fire_auto_disarm.py"
        ).write_text(
            "record_disarm_decisions(...)\n",
            encoding="utf-8",
        )
        (
            tmp_path / "core" / "automation"
            / "autonomy_armed.py"
        ).write_text("# no reader\n", encoding="utf-8")
        r = run_pattern_bc_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "arm_reads_disarm_log"
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBCReport().has_violations

    def test_with_violations(self):
        r = PatternBCReport()
        r.violations.append(PatternBCViolation(
            invariant="x", reason="broken",
        ))
        assert r.has_violations
