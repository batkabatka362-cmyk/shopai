"""Tests for engines._pattern_bf_audit (Wave 871)."""
from __future__ import annotations

from engines._pattern_bf_audit import (
    PatternBFReport,
    PatternBFViolation,
    _has_param,
    _file_references,
    run_pattern_bf_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bf_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_nine_invariants_checked(self):
        r = run_pattern_bf_audit()
        # 9 invariants per the module docstring
        assert len(r.invariants_checked) == 9


class TestHasParam:

    def test_function_with_param(self):
        def f(a, b, store_id=None):
            return None
        assert _has_param(f, "store_id")

    def test_function_without_param(self):
        def f(a, b):
            return None
        assert not _has_param(f, "store_id")


class TestFileReferences:

    def test_all_present(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text(
            "a\nb\n", encoding="utf-8",
        )
        assert _file_references(f, "a", "b")

    def test_missing(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text("a only\n", encoding="utf-8")
        assert not _file_references(f, "a", "b")


class TestSyntheticDrift:

    def test_synthetic_missing_arm_store_flag(
        self, tmp_path,
    ):
        # Build a cli.py without autonomy_arm_p --store
        (tmp_path / "cli.py").write_text(
            "autonomy_disarm_p.add_argument(\n"
            '"--store"\n'
            "autonomy_armed_p.add_argument(\n"
            '"--store"\n',
            encoding="utf-8",
        )
        r = run_pattern_bf_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "cli_arm_has_store_flag"
        ]
        assert bad

    def test_synthetic_all_three_missing(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "no per-store flags here\n",
            encoding="utf-8",
        )
        r = run_pattern_bf_audit(repo_root=tmp_path)
        missing = {
            v.invariant for v in r.violations
            if v.invariant in (
                "cli_arm_has_store_flag",
                "cli_disarm_has_store_flag",
                "cli_armed_has_store_flag",
            )
        }
        assert missing == {
            "cli_arm_has_store_flag",
            "cli_disarm_has_store_flag",
            "cli_armed_has_store_flag",
        }


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBFReport().has_violations

    def test_with_violations(self):
        r = PatternBFReport()
        r.violations.append(PatternBFViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
