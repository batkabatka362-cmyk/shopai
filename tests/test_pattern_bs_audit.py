"""Tests for engines._pattern_bs_audit (Wave 911)."""
from __future__ import annotations

from engines._pattern_bs_audit import (
    PatternBSReport,
    PatternBSViolation,
    run_pattern_bs_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bs_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_five_invariants_checked(self):
        r = run_pattern_bs_audit()
        assert len(r.invariants_checked) == 5


class TestSyntheticDrift:

    def test_synthetic_missing_thrash_block(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "# no thrash_block\n"
            "thrash_view\n"
            "store_id=store or None\n"
            'thrash_block.get("verdict")\n'
            "autonomy-overview-history --thrash\n",
            encoding="utf-8",
        )
        r = run_pattern_bs_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "empire_builds_thrash_block"
        ]
        assert bad

    def test_synthetic_missing_store_threading(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "thrash_block\n"
            '"thrash": thrash_block\n'
            'thrash_block.get("verdict")\n'
            "autonomy-overview-history --thrash\n"
            "# no thrash_view nor store_id thread\n",
            encoding="utf-8",
        )
        r = run_pattern_bs_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "history_cli_threads_store_into_thrash"
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBSReport().has_violations

    def test_with_violations(self):
        r = PatternBSReport()
        r.violations.append(PatternBSViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
