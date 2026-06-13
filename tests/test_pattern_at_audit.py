"""Tests for engines._pattern_at_audit (Wave 817)."""
from __future__ import annotations

from pathlib import Path

import pytest

from engines._pattern_at_audit import (
    PatternATReport,
    PatternATViolation,
    _EXEMPT_PATHS,
    _scan_file,
    run_pattern_at_audit,
)


class TestExemptionList:

    def test_template_is_exempt(self):
        assert (
            "core/automation/autonomy_template.py"
            in _EXEMPT_PATHS
        )

    def test_scaffolder_helpers_exempt(self):
        # autonomy_init + catalog_patches reference {{}} in
        # docstrings + literal placeholder syntax.
        assert (
            "core/automation/autonomy_init.py" in _EXEMPT_PATHS
        )
        assert (
            "core/automation/autonomy_catalog_patches.py"
            in _EXEMPT_PATHS
        )


class TestScanFile:

    def test_clean_file_no_violations(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text(
            "x = {'a': 1}\nfor i in range(3): pass\n",
            encoding="utf-8",
        )
        viols = _scan_file(f, tmp_path)
        assert viols == []

    def test_double_open_brace_flagged(self, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text(
            'x = {{"k": "v"}}\n', encoding="utf-8",
        )
        viols = _scan_file(f, tmp_path)
        # Audit only flags {{ (since }} appears in legitimate
        # nested dicts) -- 1 violation per line containing {{.
        assert len(viols) == 1
        assert viols[0].kind == "{{"

    def test_nested_dict_close_not_flagged(self, tmp_path):
        # Legitimate Python: {"a": {"b": 1}} ends with }} but
        # is NOT a scaffolder bug.
        f = tmp_path / "nested.py"
        f.write_text(
            'x = {"a": {"b": 1}}\n', encoding="utf-8",
        )
        viols = _scan_file(f, tmp_path)
        assert viols == []

    def test_line_no_captured(self, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text(
            "line1\nline2\nx = {{\nline4\n", encoding="utf-8",
        )
        viols = _scan_file(f, tmp_path)
        assert len(viols) == 1
        assert viols[0].line_no == 3

    def test_exempt_file_skipped(self, tmp_path):
        # Use a path that matches the exempt list relative to
        # tmp_path. Build the structure.
        target = (
            tmp_path / "core" / "automation"
            / "autonomy_template.py"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            'broken = {{"x": 1}}\n', encoding="utf-8",
        )
        # _scan_file's exempt list is keyed off
        # "core/automation/autonomy_template.py"
        viols = _scan_file(target, tmp_path)
        assert viols == []

    def test_unreadable_file_returns_empty(self, tmp_path):
        f = tmp_path / "nope.py"  # never created
        viols = _scan_file(f, tmp_path)
        assert viols == []


class TestRunPatternATAudit:

    def test_returns_report(self):
        r = run_pattern_at_audit()
        assert isinstance(r, PatternATReport)

    def test_live_branch_passes(self):
        # On the clean branch (post W817 fix), every scanned
        # autonomy package + core/automation file should be
        # double-brace-free.
        r = run_pattern_at_audit()
        assert not r.has_violations, [
            (v.file_path, v.line_no, v.kind)
            for v in r.violations[:10]
        ]
        assert len(r.clean_files) == len(r.files_scanned)

    def test_scans_autonomy_packages(self):
        r = run_pattern_at_audit()
        paths_str = " ".join(r.files_scanned)
        # At least one autonomy package should be in scope
        assert "_autonomy" in paths_str
        # Plus core/automation
        assert "core/automation" in paths_str

    def test_scans_at_least_10_files(self):
        r = run_pattern_at_audit()
        # 10 autonomy packages * 5 files each + core/automation
        # files = well over 50; lower bound
        assert len(r.files_scanned) >= 10


class TestSyntheticViolations:

    def test_synthetic_broken_file_flagged(self, tmp_path):
        # Plant a broken file inside a synthetic autonomy
        # package + a synthetic core/automation tree, run the
        # audit against tmp_path as root, expect a flag.
        eng = tmp_path / "engines" / "broken_autonomy"
        eng.mkdir(parents=True)
        (eng / "__init__.py").write_text("")
        (eng / "broken_applier.py").write_text(
            'def f():\n    return {{"k": 1}}\n',
            encoding="utf-8",
        )
        # Empty core/automation so the audit walks both trees
        (tmp_path / "core" / "automation").mkdir(parents=True)
        r = run_pattern_at_audit(repo_root=tmp_path)
        assert r.has_violations
        files = {v.file_path for v in r.violations}
        assert any("broken_applier.py" in f for f in files)


class TestReportDataclass:

    def test_empty_report_has_no_violations(self):
        r = PatternATReport()
        assert not r.has_violations

    def test_report_with_violations(self):
        r = PatternATReport()
        r.violations.append(PatternATViolation(
            file_path="x.py", line_no=1,
            line_excerpt="...", kind="{{",
        ))
        assert r.has_violations
