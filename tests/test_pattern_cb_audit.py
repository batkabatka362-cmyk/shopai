"""Tests for Pattern CB -- verdict + trend vocabulary drift (W963-91)."""
from __future__ import annotations

import ast

from engines._pattern_cb_audit import (
    PatternCBViolation,
    _is_rank_dict,
    _scan_rank_redefines,
    _scan_trend_literals,
    run_pattern_cb_audit,
)


# ── _is_rank_dict ─────────────────────────────────────────


def _parse_dict(src: str) -> ast.Dict:
    """Helper: parse the right-hand-side of `x = {...}`."""
    tree = ast.parse(src)
    assign = tree.body[0]
    assert isinstance(assign, ast.Assign)
    assert isinstance(assign.value, ast.Dict)
    return assign.value


class TestIsRankDict:
    def test_full_canonical(self):
        d = _parse_dict(
            'X = {"no_data": 0, "attributed_loss": 1, '
            '"organic_only": 2, "earning": 3}',
        )
        assert _is_rank_dict(d) is True

    def test_three_keys_still_matches(self):
        # Pattern is >=3 of 4 to tolerate one renamed key
        d = _parse_dict(
            'X = {"no_data": 0, "attributed_loss": 1, '
            '"organic_only": 2}',
        )
        assert _is_rank_dict(d) is True

    def test_two_keys_skips(self):
        d = _parse_dict(
            'X = {"earning": 3, "organic_only": 2}',
        )
        assert _is_rank_dict(d) is False

    def test_unrelated_dict_skips(self):
        d = _parse_dict(
            'X = {"foo": 1, "bar": 2, "baz": 3, "qux": 4}',
        )
        assert _is_rank_dict(d) is False


# ── _scan_rank_redefines ──────────────────────────────────


class TestScanRankRedefines:
    def test_canonical_module_exempt(self):
        src = (
            "VERDICT_RANK = {'no_data': 0, "
            "'attributed_loss': 1, 'organic_only': 2, "
            "'earning': 3}"
        )
        tree = ast.parse(src)
        v = _scan_rank_redefines(
            src, tree, "core/agi/verdict_vocabulary.py",
        )
        assert v == []

    def test_redefine_in_engine_violates(self):
        src = (
            "_VERDICT_RANK = {'no_data': 0, "
            "'attributed_loss': 1, 'organic_only': 2, "
            "'earning': 3}"
        )
        tree = ast.parse(src)
        v = _scan_rank_redefines(
            src, tree, "engines/some_engine/foo.py",
        )
        assert len(v) == 1
        assert v[0].rule == "rank_redefine"

    def test_alias_import_no_violation(self):
        # Importing from core.agi shouldn't trigger
        src = (
            "from core.agi.verdict_vocabulary "
            "import VERDICT_RANK as _VERDICT_RANK"
        )
        tree = ast.parse(src)
        v = _scan_rank_redefines(
            src, tree, "engines/whatever/foo.py",
        )
        assert v == []


# ── _scan_trend_literals ──────────────────────────────────


class TestScanTrendLiterals:
    def test_canonical_module_exempt(self):
        # Even though the vocabulary file CONTAINS literal
        # tokens (frozenset definitions), exempted via path.
        src = 'x = "falling" in DECLINING_TREND_TOKENS'
        tree = ast.parse(src)
        v = _scan_trend_literals(
            src, tree, "core/agi/verdict_vocabulary.py",
        )
        assert v == []

    def test_trend_falling_literal_violates(self):
        src = (
            "def x(trend):\n"
            "    if trend == 'falling':\n"
            "        return 1\n"
        )
        tree = ast.parse(src)
        v = _scan_trend_literals(
            src, tree, "engines/something/foo.py",
        )
        assert len(v) == 1
        assert v[0].rule == "trend_literal"
        assert "trend" in v[0].detail
        assert "is_declining" in v[0].detail

    def test_trend_verdict_literal_violates(self):
        src = (
            "if trend_verdict == 'declining':\n"
            "    return 1\n"
        )
        tree = ast.parse(src)
        v = _scan_trend_literals(
            src, tree, "engines/x/foo.py",
        )
        assert len(v) == 1
        # is_declining suggestion for declining/falling
        assert "is_declining" in v[0].detail

    def test_rising_literal_violates(self):
        src = (
            "if v == 'rising':\n"
            "    pass\n"
        )
        tree = ast.parse(src)
        v = _scan_trend_literals(
            src, tree, "engines/x/foo.py",
        )
        assert len(v) == 1
        assert "is_improving" in v[0].detail

    def test_unrelated_var_name_skips(self):
        # `foo == 'falling'` doesn't look trend-shaped
        src = (
            "if some_unrelated_var == 'falling':\n"
            "    pass\n"
        )
        tree = ast.parse(src)
        v = _scan_trend_literals(
            src, tree, "engines/x/foo.py",
        )
        assert v == []

    def test_unrelated_string_skips(self):
        # `trend == 'foo'` where 'foo' isn't a trend token
        src = (
            "if trend == 'something_else':\n"
            "    pass\n"
        )
        tree = ast.parse(src)
        v = _scan_trend_literals(
            src, tree, "engines/x/foo.py",
        )
        assert v == []

    def test_non_eq_comparison_skips(self):
        # `trend != 'falling'` is fine -- only `==` flags
        src = (
            "if trend != 'falling':\n"
            "    pass\n"
        )
        tree = ast.parse(src)
        v = _scan_trend_literals(
            src, tree, "engines/x/foo.py",
        )
        assert v == []


# ── run_pattern_cb_audit (live repo) ──────────────────────


class TestRunPatternCbAudit:
    def test_repo_is_clean_now(self):
        """Live trust anchor: the repo should be in the
        consolidated state. If this fails, a new file has
        drifted away from the canonical vocab."""
        report = run_pattern_cb_audit()
        assert report.has_violations is False, (
            "drift introduced: "
            + ", ".join(
                f"[{v.rule}] {v.path}:{v.line}"
                for v in report.violations
            )
        )
        assert report.files_scanned > 50

    def test_violation_carries_required_fields(self):
        src = (
            "if trend == 'falling':\n"
            "    pass\n"
        )
        tree = ast.parse(src)
        v = _scan_trend_literals(
            src, tree, "engines/x/foo.py",
        )
        assert isinstance(v[0], PatternCBViolation)
        assert v[0].rule
        assert v[0].path
        assert v[0].line == 1
        assert v[0].detail
