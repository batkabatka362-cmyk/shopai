"""Tests for engines._pattern_bz_audit (Wave 935)."""
from __future__ import annotations

from engines._pattern_bz_audit import (
    PatternBZReport,
    PatternBZViolation,
    run_pattern_bz_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bz_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_three_invariants_checked(self):
        r = run_pattern_bz_audit()
        assert len(r.invariants_checked) == 3


class TestSyntheticDrift:

    def test_synthetic_missing_recent_blocks(
        self, tmp_path,
    ):
        (tmp_path / "cli.py").write_text(
            "# no recent_blocks import\n"
            '"  Thrash blocks:"\n'
            "shopai thrash-blocks\n",
            encoding="utf-8",
        )
        r = run_pattern_bz_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "daily_brief_imports_recent_blocks"
        ]
        assert bad

    def test_synthetic_missing_row_prefix(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "recent_blocks\nthrash_block_log\n"
            "shopai thrash-blocks\n"
            "# no row prefix\n",
            encoding="utf-8",
        )
        r = run_pattern_bz_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "daily_brief_renders_blocks_row"
        ]
        assert bad

    def test_synthetic_missing_drill_hint(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "recent_blocks\nthrash_block_log\n"
            '"  Thrash blocks:"\n',
            encoding="utf-8",
        )
        r = run_pattern_bz_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "daily_brief_shows_drill_hint"
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBZReport().has_violations

    def test_with_violations(self):
        r = PatternBZReport()
        r.violations.append(PatternBZViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
