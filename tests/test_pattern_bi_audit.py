"""Tests for engines._pattern_bi_audit (Wave 880)."""
from __future__ import annotations

from engines._pattern_bi_audit import (
    PatternBIReport,
    PatternBIViolation,
    run_pattern_bi_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bi_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_four_invariants_checked(self):
        r = run_pattern_bi_audit()
        assert len(r.invariants_checked) == 4


class TestSyntheticDrift:

    def test_synthetic_no_adopter(self, tmp_path):
        # Build a tree where discoverers exist but none
        # reference the helper.
        d = tmp_path / "core" / "automation" / "discoverers"
        d.mkdir(parents=True)
        (d / "foo.py").write_text(
            "# helper-free comment\n",
            encoding="utf-8",
        )
        r = run_pattern_bi_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == (
                "at_least_one_discoverer_adopts_helper"
            )
        ]
        assert bad

    def test_synthetic_adopter_via_helper_name(self, tmp_path):
        d = tmp_path / "core" / "automation" / "discoverers"
        d.mkdir(parents=True)
        (d / "good.py").write_text(
            "from core.automation.discoverer_env "
            "import resolve_int\n",
            encoding="utf-8",
        )
        r = run_pattern_bi_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == (
                "at_least_one_discoverer_adopts_helper"
            )
        ]
        assert not bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBIReport().has_violations

    def test_with_violations(self):
        r = PatternBIReport()
        r.violations.append(PatternBIViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
