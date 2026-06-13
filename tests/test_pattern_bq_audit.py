"""Tests for engines._pattern_bq_audit (Wave 902)."""
from __future__ import annotations

from engines._pattern_bq_audit import (
    PatternBQReport,
    PatternBQViolation,
    _EXPECTED_ENTRY_FIELDS,
    run_pattern_bq_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bq_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_five_invariants_checked(self):
        r = run_pattern_bq_audit()
        assert len(r.invariants_checked) == 5


class TestExpectedSchema:

    def test_expected_entry_fields_complete(self):
        assert "captured_at" in _EXPECTED_ENTRY_FIELDS
        assert "verdict" in _EXPECTED_ENTRY_FIELDS
        assert "armed_total" in _EXPECTED_ENTRY_FIELDS


class TestSyntheticDrift:

    def test_synthetic_missing_subparser(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "# no autonomy_overview_history_p subparser\n"
            '"--transitions"\n',
            encoding="utf-8",
        )
        r = run_pattern_bq_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "cli_history_subparser_registered"
        ]
        assert bad

    def test_synthetic_missing_transitions(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            "autonomy_overview_history_p = sub.add_parser(\n"
            '    "autonomy-overview-history"\n'
            ")\n"
            "autonomy_overview_history_p.add_argument(\n"
            '    "--limit"\n'
            ")\n",
            encoding="utf-8",
        )
        r = run_pattern_bq_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "cli_registers_transitions_flag"
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBQReport().has_violations

    def test_with_violations(self):
        r = PatternBQReport()
        r.violations.append(PatternBQViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
