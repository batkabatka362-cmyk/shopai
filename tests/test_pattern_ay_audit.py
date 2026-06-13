"""Tests for engines._pattern_ay_audit (Wave 836)."""
from __future__ import annotations

import pytest

from engines._pattern_ay_audit import (
    PatternAYReport,
    PatternAYViolation,
    _has_test_functions,
    run_pattern_ay_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_ay_audit()
        assert not r.has_violations, [
            (v.domain, v.reason) for v in r.violations
        ]
        # All 8 discoverers have test files
        assert len(r.clean_discoverers) == 8

    def test_all_8_scanned(self):
        r = run_pattern_ay_audit()
        assert len(r.discoverers_scanned) == 8


class TestHasTestFunctions:

    def test_file_with_test_def_passes(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text(
            "def test_foo():\n    pass\n",
            encoding="utf-8",
        )
        assert _has_test_functions(f)

    def test_file_with_class_test_method_passes(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text(
            "class TestX:\n"
            "    def test_bar(self):\n"
            "        pass\n",
            encoding="utf-8",
        )
        assert _has_test_functions(f)

    def test_file_with_no_test_def_fails(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text(
            "def foo():\n    pass\n",
            encoding="utf-8",
        )
        assert not _has_test_functions(f)

    def test_unparseable_file_returns_false(self, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text(
            "this is not valid python (((",
            encoding="utf-8",
        )
        assert not _has_test_functions(f)


class TestSyntheticDrift:

    def test_missing_test_file_flagged(
        self, tmp_path, monkeypatch,
    ):
        # Build a synthetic repo with no test files; assert
        # every discoverer is flagged.
        monkeypatch.chdir(tmp_path)
        # The audit reads from registered_domains() so even
        # in tmp_path the real catalog stays the same.
        r = run_pattern_ay_audit(repo_root=tmp_path)
        assert r.has_violations
        # All 8 discoverers should be flagged
        assert len(r.violations) == 8
        for v in r.violations:
            assert "missing" in v.reason

    def test_empty_test_file_flagged(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (
            tmp_path / "tests" / "test_discoverer_shipping_alert.py"
        ).write_text(
            "# no tests in here\n",
            encoding="utf-8",
        )
        r = run_pattern_ay_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.domain == "shipping_alert"
        ]
        assert bad
        assert "no test_*" in bad[0].reason


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternAYReport().has_violations

    def test_with_violations(self):
        r = PatternAYReport()
        r.violations.append(PatternAYViolation(
            domain="x", reason="missing",
        ))
        assert r.has_violations
