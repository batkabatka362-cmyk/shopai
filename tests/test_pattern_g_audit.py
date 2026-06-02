"""Tests for the Pattern G (or-coercion silent drop) audit.

Pattern G is the recurring class: ``X.get("k") or DEFAULT``
silently drops legitimate falsy values (0 / "" / False).
Caught live W947 + W962-11 + W962-12. The audit is advisory:
it surfaces candidates for human review without failing CI.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _make_module(tmp_path: Path, name: str, body: str) -> Path:
    pkg = tmp_path / name
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    target = pkg / "flow.py"
    target.write_text(body, encoding="utf-8")
    return target


class TestPatternGAudit:

    def test_clean_tree_no_violations(self, tmp_path):
        from engines._pattern_g_audit import audit_pattern_g
        _make_module(
            tmp_path, "clean",
            "def f(d):\n"
            "    return d.get('foo')\n",
        )
        report = audit_pattern_g(roots=(tmp_path,))
        assert report.has_violations is False
        assert len(report.violations) == 0

    def test_numeric_default_flagged(self, tmp_path):
        """The W962-11 trap: amount=0 dropped by `or 100`."""
        from engines._pattern_g_audit import audit_pattern_g
        _make_module(
            tmp_path, "spend_engine",
            "def f(params):\n"
            "    return params.get('ad_spend') or 100\n",
        )
        report = audit_pattern_g(roots=(tmp_path,))
        assert len(report.violations) == 1
        v = report.violations[0]
        assert v.key == "ad_spend"
        assert v.classification == "numeric_default"

    def test_string_default_flagged(self, tmp_path):
        from engines._pattern_g_audit import audit_pattern_g
        _make_module(
            tmp_path, "country_engine",
            "def f(req):\n"
            "    return req.get('country_total') or 'US'\n",
        )
        report = audit_pattern_g(roots=(tmp_path,))
        assert len(report.violations) == 1
        v = report.violations[0]
        assert v.classification == "string_default"

    def test_zero_default_not_flagged(self, tmp_path):
        """`or 0` chains are typically intentional (treat falsy
        as zero); the audit ignores them."""
        from engines._pattern_g_audit import audit_pattern_g
        _make_module(
            tmp_path, "zero_default",
            "def f(d):\n"
            "    return d.get('amount') or 0\n",
        )
        report = audit_pattern_g(roots=(tmp_path,))
        assert len(report.violations) == 0

    def test_bool_default_not_flagged(self, tmp_path):
        """`or True` / `or False` are usually flag toggles, not
        Pattern G bugs."""
        from engines._pattern_g_audit import audit_pattern_g
        _make_module(
            tmp_path, "bool_default",
            "def f(d):\n"
            "    return d.get('amount') or True\n",
        )
        report = audit_pattern_g(roots=(tmp_path,))
        assert len(report.violations) == 0

    def test_non_risky_key_not_flagged(self, tmp_path):
        """The heuristic only flags keys whose name suggests
        a numeric / string value field. Other keys pass through."""
        from engines._pattern_g_audit import audit_pattern_g
        _make_module(
            tmp_path, "non_risky",
            "def f(d):\n"
            "    return d.get('xyz_handler') or 'default_handler'\n",
        )
        report = audit_pattern_g(roots=(tmp_path,))
        # xyz_handler doesn't match risky tokens
        assert len(report.violations) == 0

    def test_multiple_violations(self, tmp_path):
        from engines._pattern_g_audit import audit_pattern_g
        _make_module(
            tmp_path, "many",
            "def f(d):\n"
            "    a = d.get('amount') or 100\n"
            "    b = d.get('trial_days') or 14\n"
            "    c = d.get('quantity') or 1\n",
        )
        report = audit_pattern_g(roots=(tmp_path,))
        assert len(report.violations) == 3
        keys = {v.key for v in report.violations}
        assert keys == {"amount", "trial_days", "quantity"}

    def test_audit_module_self_skip(self, tmp_path):
        """The audit module itself contains the _RISKY_KEY_TOKENS
        literal list; ensure the walker skips its own source so
        it doesn't self-flag."""
        from engines._pattern_g_audit import audit_pattern_g
        # Run against the real engines/ tree
        report = audit_pattern_g()
        files = {v.file for v in report.violations}
        for f in files:
            assert "_pattern_g_audit.py" not in f

    def test_scanned_files_count(self, tmp_path):
        from engines._pattern_g_audit import audit_pattern_g
        _make_module(tmp_path, "a", "x = 1\n")
        _make_module(tmp_path, "b", "y = 2\n")
        report = audit_pattern_g(roots=(tmp_path,))
        # 2 packages × (__init__.py + flow.py) = 4
        assert report.scanned_files == 4
