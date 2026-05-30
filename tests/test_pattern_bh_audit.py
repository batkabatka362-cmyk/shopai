"""Tests for engines._pattern_bh_audit (Wave 877)."""
from __future__ import annotations

from engines._pattern_bh_audit import (
    PatternBHReport,
    PatternBHViolation,
    _file_references,
    _has_param,
    run_pattern_bh_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bh_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_four_invariants_checked(self):
        r = run_pattern_bh_audit()
        # 4 invariants per the module docstring
        assert len(r.invariants_checked) == 4


class TestHasParam:

    def test_function_with_param(self):
        def f(a, store_id=None):
            return None
        assert _has_param(f, "store_id")

    def test_function_without_param(self):
        def f(a):
            return None
        assert not _has_param(f, "store_id")


class TestFileReferences:

    def test_present(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text("a\nb\n", encoding="utf-8")
        assert _file_references(f, "a", "b")

    def test_missing(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text("a only\n", encoding="utf-8")
        assert not _file_references(f, "a", "b")


class TestSyntheticDrift:

    def test_synthetic_missing_arm_forward(self, tmp_path):
        (tmp_path / "core" / "automation").mkdir(parents=True)
        (
            tmp_path / "core" / "automation"
            / "autonomy_armed.py"
        ).write_text(
            "no last_disarm_at call here\n",
            encoding="utf-8",
        )
        (tmp_path / "cli.py").write_text(
            "autonomy_disarm_hist_p.add_argument(\n"
            '"--store"\n',
            encoding="utf-8",
        )
        r = run_pattern_bh_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == (
                "arm_forwards_store_id_to_last_disarm_at"
            )
        ]
        assert bad

    def test_synthetic_missing_cli_flag(self, tmp_path):
        (tmp_path / "core" / "automation").mkdir(parents=True)
        (
            tmp_path / "core" / "automation"
            / "autonomy_armed.py"
        ).write_text(
            "last_disarm_at\nstore_id=\n",
            encoding="utf-8",
        )
        (tmp_path / "cli.py").write_text(
            "no per-store flag here\n", encoding="utf-8",
        )
        r = run_pattern_bh_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == (
                "cli_disarm_history_has_store_flag"
            )
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBHReport().has_violations

    def test_with_violations(self):
        r = PatternBHReport()
        r.violations.append(PatternBHViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
