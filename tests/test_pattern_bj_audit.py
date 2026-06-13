"""Tests for engines._pattern_bj_audit (Wave 884)."""
from __future__ import annotations

from engines._pattern_bj_audit import (
    PatternBJReport,
    PatternBJViolation,
    run_pattern_bj_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bj_audit()
        assert not r.has_violations, [
            (v.discoverer, v.reason) for v in r.violations
        ]

    def test_8_discoverers_clean(self):
        r = run_pattern_bj_audit()
        # 8 substrate-mode discoverers all migrated W881-W883
        assert len(r.clean_discoverers) == 8

    def test_scans_match_clean(self):
        r = run_pattern_bj_audit()
        assert len(r.discoverers_scanned) == 8


class TestSyntheticDrift:

    def test_synthetic_unmigrated_flagged(self, tmp_path):
        d = tmp_path / "core" / "automation" / "discoverers"
        d.mkdir(parents=True)
        (d / "bad.py").write_text(
            "import os\n"
            "x = os.environ.get('SOMETHING', '')\n",
            encoding="utf-8",
        )
        r = run_pattern_bj_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.discoverer == "bad"
        ]
        assert bad

    def test_synthetic_migrated_clean(self, tmp_path):
        d = tmp_path / "core" / "automation" / "discoverers"
        d.mkdir(parents=True)
        (d / "good.py").write_text(
            "from core.automation.discoverer_env "
            "import resolve_int\n",
            encoding="utf-8",
        )
        r = run_pattern_bj_audit(repo_root=tmp_path)
        assert "good" in r.clean_discoverers
        assert not r.has_violations

    def test_missing_dir_flagged(self, tmp_path):
        r = run_pattern_bj_audit(repo_root=tmp_path)
        assert r.has_violations
        assert any(
            "directory not found" in v.reason
            for v in r.violations
        )

    def test_init_py_skipped(self, tmp_path):
        d = tmp_path / "core" / "automation" / "discoverers"
        d.mkdir(parents=True)
        (d / "__init__.py").write_text(
            "# no helper reference\n",
            encoding="utf-8",
        )
        r = run_pattern_bj_audit(repo_root=tmp_path)
        # No discoverers scanned + no violations
        assert "__init__" not in r.discoverers_scanned


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBJReport().has_violations

    def test_with_violations(self):
        r = PatternBJReport()
        r.violations.append(PatternBJViolation(
            discoverer="x", reason="y",
        ))
        assert r.has_violations
