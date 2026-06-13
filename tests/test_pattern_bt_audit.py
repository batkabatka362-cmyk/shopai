"""Tests for engines._pattern_bt_audit (Wave 914)."""
from __future__ import annotations

from engines._pattern_bt_audit import (
    PatternBTReport,
    PatternBTViolation,
    run_pattern_bt_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bt_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_five_invariants_checked(self):
        r = run_pattern_bt_audit()
        assert len(r.invariants_checked) == 5


class TestSyntheticDrift:

    def test_synthetic_missing_above_threshold_flag(
        self, tmp_path,
    ):
        (tmp_path / "cli.py").write_text(
            "# no --above-threshold flag\n"
            "above_threshold\n"
            'b.density_label\n'
            '("elevated", "thrashing")\n'
            '"above_threshold": above_only\n'
            'thrash_block["per_store"]\n'
            "store_id=s[\"store_id\"]\n"
            "thrash per-store:\n"
            "--thrash [--store X]\n",
            encoding="utf-8",
        )
        r = run_pattern_bt_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "cli_registers_above_threshold_flag"
        ]
        assert bad

    def test_synthetic_missing_per_store_breakdown(
        self, tmp_path,
    ):
        (tmp_path / "cli.py").write_text(
            "autonomy_overview_history_p.add_argument\n"
            '"--above-threshold"\n'
            "above_threshold\n"
            'b.density_label\n'
            '("elevated", "thrashing")\n'
            '"above_threshold": above_only\n'
            "# no per_store breakdown\n"
            "thrash per-store:\n"
            "--thrash [--store X]\n",
            encoding="utf-8",
        )
        r = run_pattern_bt_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "empire_builds_per_store_breakdown"
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBTReport().has_violations

    def test_with_violations(self):
        r = PatternBTReport()
        r.violations.append(PatternBTViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
