"""Tests for Pattern CC -- persistence helpers drift (W963-92)."""
from __future__ import annotations

import ast
from unittest.mock import patch

from engines._pattern_cc_audit import (
    PatternCCViolation,
    _MIGRATED_FILES,
    _redefines_guard,
    _uses_mkstemp,
    run_pattern_cc_audit,
)


# ── _redefines_guard ──────────────────────────────────────


class TestRedefinesGuard:
    def test_clean_module(self):
        src = (
            "from core.agi.persistence import "
            "is_test_environment as _is_test_environment\n"
        )
        redef, line = _redefines_guard(ast.parse(src))
        assert redef is False
        assert line == 0

    def test_local_def_violates(self):
        src = (
            "def _is_test_environment():\n"
            "    return False\n"
        )
        redef, line = _redefines_guard(ast.parse(src))
        assert redef is True
        assert line == 1

    def test_nested_def_not_flagged(self):
        # Only top-level functions count.
        src = (
            "def outer():\n"
            "    def _is_test_environment():\n"
            "        return True\n"
        )
        redef, line = _redefines_guard(ast.parse(src))
        assert redef is False


# ── _uses_mkstemp ─────────────────────────────────────────


class TestUsesMkstemp:
    def test_clean_module(self):
        src = (
            "from core.agi.persistence import "
            "atomic_write_json\n"
            "atomic_write_json('p', [])\n"
        )
        used, line = _uses_mkstemp(ast.parse(src))
        assert used is False

    def test_qualified_call_violates(self):
        src = (
            "import tempfile\n"
            "tempfile.mkstemp(prefix='.x')\n"
        )
        used, line = _uses_mkstemp(ast.parse(src))
        assert used is True
        assert line == 2

    def test_bare_import_violates(self):
        src = (
            "from tempfile import mkstemp\n"
            "mkstemp(prefix='.x')\n"
        )
        used, line = _uses_mkstemp(ast.parse(src))
        assert used is True
        assert line == 2


# ── _MIGRATED_FILES set sanity ────────────────────────────


class TestMigratedFiles:
    def test_seven_files_listed(self):
        # W963-92 migrated exactly 7 modules
        assert len(_MIGRATED_FILES) == 7

    def test_all_paths_are_repo_relative_python(self):
        for path in _MIGRATED_FILES:
            assert path.endswith(".py")
            assert path.startswith("engines/")


# ── run_pattern_cc_audit (live) ────────────────────────────


class TestRunPatternCcAudit:
    def test_repo_is_clean_now(self):
        """Trust anchor: if this fails, one of the
        migrated modules drifted."""
        report = run_pattern_cc_audit()
        assert report.files_checked == 7
        assert report.has_violations is False, (
            "drift: "
            + ", ".join(
                f"[{v.rule}] {v.path}:{v.line}"
                for v in report.violations
            )
        )

    def test_missing_file_violation(self):
        with patch(
            "engines._pattern_cc_audit._MIGRATED_FILES",
            frozenset({"engines/nonexistent/foo.py"}),
        ):
            report = run_pattern_cc_audit()
        assert report.has_violations is True
        assert any(
            v.rule == "missing_file"
            for v in report.violations
        )

    def test_violation_carries_required_fields(self):
        # Use the bare-import path to synthesize a
        # violation without touching real files.
        src = "from tempfile import mkstemp\nmkstemp()\n"
        used, line = _uses_mkstemp(ast.parse(src))
        assert used is True
        v = PatternCCViolation(
            rule="uses_mkstemp",
            path="engines/x.py",
            line=line,
            detail="x",
        )
        assert v.rule
        assert v.path
        assert v.line == 2
