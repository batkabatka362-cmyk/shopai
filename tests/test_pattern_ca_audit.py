"""Tests for Pattern CA -- Phase 4 substrate wiring audit (W963-67/74)."""
from __future__ import annotations

from unittest.mock import patch

from engines._pattern_ca_audit import (
    PatternCAViolation,
    _ast_parses,
    _check_probe,
    _find_function,
    _function_source,
    _parse,
    _PROBES,
    run_pattern_ca_audit,
)


class TestAstParses:
    def test_valid_source(self):
        assert _ast_parses("x = 1") is True

    def test_syntax_error(self):
        assert _ast_parses("def x(:") is False

    def test_empty_string(self):
        assert _ast_parses("") is True


# ── _find_function ────────────────────────────────────────


class TestFindFunction:
    def test_finds_top_level(self):
        src = "def foo():\n    return 1\n"
        tree = _parse(src)
        fn = _find_function(tree, "foo")
        assert fn is not None
        assert fn.name == "foo"

    def test_returns_none_when_absent(self):
        src = "def bar():\n    return 1\n"
        tree = _parse(src)
        assert _find_function(tree, "foo") is None

    def test_does_not_match_nested(self):
        # Only top-level fns are findable -- this is by
        # design so probes scope correctly.
        src = (
            "def outer():\n"
            "    def inner():\n"
            "        return 1\n"
            "    return inner\n"
        )
        tree = _parse(src)
        assert _find_function(tree, "inner") is None
        assert _find_function(tree, "outer") is not None


# ── _function_source ──────────────────────────────────────


class TestFunctionSource:
    def test_extracts_body(self):
        src = (
            "x = 1\n"
            "def foo():\n"
            "    needle\n"
            "    return\n"
            "y = 2\n"
        )
        tree = _parse(src)
        fn = _find_function(tree, "foo")
        body = _function_source(src, fn)
        assert "needle" in body
        assert "x = 1" not in body
        assert "y = 2" not in body


# ── _check_probe (function-scope) ─────────────────────────


class TestCheckProbeFunctionScope:
    def test_needle_inside_function_ok(self):
        src = (
            "def _cmd_daily_brief(args):\n"
            "    from engines.agi_anomaly_detector "
            "import detect\n"
        )
        tree = _parse(src)
        probe = {
            "name": "x",
            "path": "cli.py",
            "enclosing_function": "_cmd_daily_brief",
            "needles": ("agi_anomaly_detector",),
            "min_occurrences": 1,
        }
        ok, missing = _check_probe(probe, src, tree)
        assert ok is True
        assert missing == []

    def test_needle_outside_function_fails(self):
        """Bug 2 (W963-72) regression: needle present in
        wrong function should FAIL."""
        src = (
            "def _cmd_daily_brief(args):\n"
            "    pass\n"
            "\n"
            "def _cmd_empire(args):\n"
            "    from engines.agi_anomaly_detector "
            "import detect\n"
        )
        tree = _parse(src)
        probe = {
            "name": "x",
            "path": "cli.py",
            "enclosing_function": "_cmd_daily_brief",
            "needles": ("agi_anomaly_detector",),
            "min_occurrences": 1,
        }
        ok, missing = _check_probe(probe, src, tree)
        assert ok is False
        assert "agi_anomaly_detector" in missing

    def test_missing_function_fails(self):
        src = "def _cmd_other(args):\n    pass\n"
        tree = _parse(src)
        probe = {
            "name": "x",
            "path": "cli.py",
            "enclosing_function": "_cmd_daily_brief",
            "needles": ("x",),
            "min_occurrences": 1,
        }
        ok, missing = _check_probe(probe, src, tree)
        assert ok is False
        assert any("not found" in m for m in missing)


class TestCheckProbeFileScope:
    def test_needle_anywhere_in_file_ok(self):
        src = "_agi_phase4_context()\n_agi_phase4_context()\n"
        tree = _parse(src)
        probe = {
            "name": "x",
            "path": "any.py",
            "needles": ("_agi_phase4_context",),
            "min_occurrences": 2,
        }
        ok, missing = _check_probe(probe, src, tree)
        assert ok is True

    def test_below_minimum_fails(self):
        src = "_agi_phase4_context()\n"
        tree = _parse(src)
        probe = {
            "name": "x",
            "path": "any.py",
            "needles": ("_agi_phase4_context",),
            "min_occurrences": 2,
        }
        ok, missing = _check_probe(probe, src, tree)
        assert ok is False
        assert any("total occurrences" in m for m in missing)


# ── run_pattern_ca_audit ──────────────────────────────────


class TestRunPatternCaAudit:
    def test_real_repo_is_clean(self):
        report = run_pattern_ca_audit()
        assert report.has_violations is False, (
            f"Pattern CA violations: "
            + ", ".join(
                f"[{v.surface}] {v.path}: {v.detail}"
                for v in report.violations
            )
        )
        # 18 probes after W963-79:
        #   10 cli.py function-scope (daily-brief x3,
        #     empire x3, morning-brief x1, cycle-run x1,
        #     cycle-status x1, reconcile x1)
        #   3 _notify (anomaly + streak + brief-diff)
        #   1 _ai_strategies (helper)
        #   1 world_model (section)
        #   1 _go_live_check (probe)
        #   2 morning_brief/briefer (diff + attention)
        assert report.probes_run == 18
        assert report.clean_probes == 18

    def test_missing_file_violates(self):
        with patch(
            "engines._pattern_ca_audit._read",
            return_value="",
        ):
            report = run_pattern_ca_audit()
        assert report.has_violations is True
        # 18 probes all hit the empty source
        assert len(report.violations) == 18
        for v in report.violations:
            assert "missing" in v.detail.lower()

    def test_syntax_error_violates(self):
        with patch(
            "engines._pattern_ca_audit._read",
            return_value="def f(:",
        ):
            report = run_pattern_ca_audit()
        assert report.has_violations is True
        for v in report.violations:
            assert "syntaxerror" in v.detail.lower()

    def test_missing_needle_violates(self):
        # Source parses, but no Phase 4 references in it
        with patch(
            "engines._pattern_ca_audit._read",
            return_value="x = 1\n",
        ):
            report = run_pattern_ca_audit()
        assert report.has_violations is True
        for v in report.violations:
            # Either "missing needles" or "not found"
            d = v.detail.lower()
            assert (
                "missing" in d
                or "not found" in d
            )

    def test_violation_carries_surface_and_path(self):
        with patch(
            "engines._pattern_ca_audit._read",
            return_value="x = 1",
        ):
            report = run_pattern_ca_audit()
        for v in report.violations:
            assert isinstance(v, PatternCAViolation)
            assert v.surface
            assert v.path

    def test_function_scope_violation_message(self):
        """Bug 2 regression: violation detail should
        mention the enclosing function."""
        # Source with empty _cmd_daily_brief but the needle
        # elsewhere
        fake_src = (
            "def _cmd_daily_brief(args):\n"
            "    pass\n"
            "def _cmd_empire(args):\n"
            "    from engines.agi_anomaly_detector "
            "import detect\n"
            "    from engines.agi_recommend_streak "
            "import detect_streaks\n"
            "    from engines.agi_earnings_summary "
            "import compute_summary\n"
            "def _cmd_morning_brief(args):\n"
            "    AgiMorningBriefEngine()\n"
            "def _cmd_cycle_run(args):\n"
            "    SHOPAI_CYCLE_RECORD_BRIEF = 1\n"
        )
        with patch(
            "engines._pattern_ca_audit._read",
            lambda path: (
                fake_src if path.name == "cli.py" else ""
            ),
        ):
            report = run_pattern_ca_audit()
        # daily-brief probes should fail with "inside" hint
        daily_brief_violations = [
            v for v in report.violations
            if v.surface.startswith("cli_daily_brief")
        ]
        assert len(daily_brief_violations) >= 1
        for v in daily_brief_violations:
            assert "_cmd_daily_brief" in v.detail
