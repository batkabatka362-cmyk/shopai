"""Tests for engines._pattern_br_audit (Wave 908)."""
from __future__ import annotations

from engines._pattern_br_audit import (
    PatternBRReport,
    PatternBRViolation,
    _THRASH_VERDICTS,
    run_pattern_br_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_br_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_six_invariants_checked(self):
        r = run_pattern_br_audit()
        assert len(r.invariants_checked) == 6


class TestExpectedVerdicts:

    def test_canonical_set(self):
        assert _THRASH_VERDICTS == {
            "calm", "elevated", "thrashing",
        }


class TestSyntheticDrift:

    def test_synthetic_missing_thrash_flag(self, tmp_path):
        # Make cli.py + notify.py path
        (tmp_path / "cli.py").write_text(
            "# no --thrash flag\n"
            "compute_thrash\n"
            "autonomy-overview-history --thrash\n",
            encoding="utf-8",
        )
        (tmp_path / "engines").mkdir()
        (tmp_path / "engines" / "_notify.py").write_text(
            '"autonomy_thrash"\n'
            '"autonomy_thrash_elevated"\n',
            encoding="utf-8",
        )
        r = run_pattern_br_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "cli_registers_thrash_flag"
        ]
        assert bad

    def test_synthetic_missing_notify_kinds(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "autonomy_overview_history_p.add_argument\n"
            '"--thrash"\n'
            "compute_thrash\n"
            "autonomy-overview-history --thrash\n",
            encoding="utf-8",
        )
        (tmp_path / "engines").mkdir()
        (tmp_path / "engines" / "_notify.py").write_text(
            "# no thrash kinds\n",
            encoding="utf-8",
        )
        r = run_pattern_br_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "notify_registers_thrash_alerts"
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBRReport().has_violations

    def test_with_violations(self):
        r = PatternBRReport()
        r.violations.append(PatternBRViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
