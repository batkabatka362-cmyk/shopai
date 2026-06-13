"""Tests for engines._pattern_bm_audit (Wave 891)."""
from __future__ import annotations

from engines._pattern_bm_audit import (
    PatternBMReport,
    PatternBMViolation,
    _file_references,
    run_pattern_bm_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bm_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_four_invariants_checked(self):
        r = run_pattern_bm_audit()
        assert len(r.invariants_checked) == 4


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

    def test_synthetic_no_flag_flagged(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "no --store flag here\n", encoding="utf-8",
        )
        r = run_pattern_bm_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "cli_autonomy_env_has_store_flag"
        ]
        assert bad

    def test_synthetic_no_store_token_flagged(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            'autonomy_env_p.add_argument\n"--store"\n'
            "_cmd_autonomy_env\n"
            "# bare comment without the marker\n",
            encoding="utf-8",
        )
        r = run_pattern_bm_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == (
                "handler_references_store_token"
            )
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBMReport().has_violations

    def test_with_violations(self):
        r = PatternBMReport()
        r.violations.append(PatternBMViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
