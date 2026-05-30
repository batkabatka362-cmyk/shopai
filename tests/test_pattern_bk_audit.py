"""Tests for engines._pattern_bk_audit (Wave 886)."""
from __future__ import annotations

from engines._pattern_bk_audit import (
    PatternBKReport,
    PatternBKViolation,
    _file_references,
    run_pattern_bk_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bk_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_three_invariants_checked(self):
        r = run_pattern_bk_audit()
        # 3 invariants per the module docstring
        assert len(r.invariants_checked) == 3


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

    def test_synthetic_missing_flag(self, tmp_path):
        # cli.py without autonomy_discover_p --store
        (tmp_path / "cli.py").write_text(
            "_cmd_autonomy_discover\nstore_id=\n",
            encoding="utf-8",
        )
        r = run_pattern_bk_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "cli_discover_has_store_flag"
        ]
        assert bad

    def test_synthetic_missing_plumb(self, tmp_path):
        # cli.py registers --store but handler doesn't pass
        # store_id=
        (tmp_path / "cli.py").write_text(
            "autonomy_discover_p.add_argument\n"
            '"--store"\n',
            encoding="utf-8",
        )
        r = run_pattern_bk_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "cli_discover_plumbs_store_id"
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBKReport().has_violations

    def test_with_violations(self):
        r = PatternBKReport()
        r.violations.append(PatternBKViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
