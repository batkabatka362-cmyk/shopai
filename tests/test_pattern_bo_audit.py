"""Tests for engines._pattern_bo_audit (Wave 895)."""
from __future__ import annotations

from engines._pattern_bo_audit import (
    PatternBOReport,
    PatternBOViolation,
    _file_references,
    run_pattern_bo_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bo_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_three_invariants_checked(self):
        r = run_pattern_bo_audit()
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

    def test_synthetic_missing_build_overview(
        self, tmp_path,
    ):
        (tmp_path / "cli.py").write_text(
            '"  Autonomy:"\nshopai autonomy-overview\n'
            "# no build_overview ref\n",
            encoding="utf-8",
        )
        r = run_pattern_bo_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == (
                "daily_brief_imports_build_overview"
            )
        ]
        assert bad

    def test_synthetic_missing_row_prefix(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "build_overview\ndaily-brief\n"
            "shopai autonomy-overview\n"
            "# no autonomy row label\n",
            encoding="utf-8",
        )
        r = run_pattern_bo_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "daily_brief_renders_autonomy_row"
        ]
        assert bad

    def test_synthetic_missing_drill_hint(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "build_overview\ndaily-brief\n"
            '"  Autonomy:"\n',
            encoding="utf-8",
        )
        r = run_pattern_bo_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "daily_brief_shows_drill_hint"
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBOReport().has_violations

    def test_with_violations(self):
        r = PatternBOReport()
        r.violations.append(PatternBOViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
