"""Tests for engines._pattern_bx_audit (Wave 929)."""
from __future__ import annotations

from engines._pattern_bx_audit import (
    PatternBXReport,
    PatternBXViolation,
    run_pattern_bx_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bx_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_three_invariants_checked(self):
        r = run_pattern_bx_audit()
        assert len(r.invariants_checked) == 3


class TestSyntheticDrift:

    def test_synthetic_missing_envelope_key(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "guardrail_override_block\n"
            "thrash_guardrail_enabled\n"
            "guardrail-override:\n"
            "shopai thrash-guardrail\n"
            "# no envelope key\n",
            encoding="utf-8",
        )
        r = run_pattern_bx_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "json_envelope_carries_overrides"
        ]
        assert bad

    def test_synthetic_missing_drill_hint(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "guardrail_override_block\n"
            "thrash_guardrail_enabled\n"
            '"guardrail_overrides": guardrail_override_block\n'
            "# no drill hint\n",
            encoding="utf-8",
        )
        r = run_pattern_bx_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "renders_override_row_with_drill"
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBXReport().has_violations

    def test_with_violations(self):
        r = PatternBXReport()
        r.violations.append(PatternBXViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
