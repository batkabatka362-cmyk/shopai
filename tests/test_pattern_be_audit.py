"""Tests for engines._pattern_be_audit (Wave 867)."""
from __future__ import annotations

from engines._pattern_be_audit import (
    PatternBEReport,
    PatternBEViolation,
    _file_references,
    run_pattern_be_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_be_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_five_invariants_checked(self):
        r = run_pattern_be_audit()
        # 5 invariants per the module docstring
        assert len(r.invariants_checked) == 5


class TestFileReferences:

    def test_all_present(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text(
            "from y import a, b\n", encoding="utf-8",
        )
        assert _file_references(f, "a", "b")

    def test_missing(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text("only_a\n", encoding="utf-8")
        assert not _file_references(f, "a", "b")


class TestSyntheticDrift:

    def test_synthetic_missing_cli_passes_domain(
        self, tmp_path,
    ):
        # Build a tree where cli.py never calls _cd_hours(d).
        (tmp_path / "cli.py").write_text(
            "_cd_hours()  # no domain arg\n",
            encoding="utf-8",
        )
        (tmp_path / "core" / "automation").mkdir(parents=True)
        (
            tmp_path / "core" / "automation"
            / "autonomy_armed.py"
        ).write_text(
            "SHOPAI_AUTO_DISARM_COOLDOWN_HOURS = ''\n"
            "SHOPAI_AUTO_DISARM_COOLDOWN_X_HOURS = ''\n",
            encoding="utf-8",
        )
        (
            tmp_path / "core" / "automation"
            / "autonomy_doctor.py"
        ).write_text(
            "_cd_hours(summary.name)\n", encoding="utf-8",
        )
        r = run_pattern_be_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "cli_passes_domain_to_cooldown"
        ]
        assert bad

    def test_synthetic_missing_doctor_passes_domain(
        self, tmp_path,
    ):
        (tmp_path / "cli.py").write_text(
            "_cd_hours(d)\n", encoding="utf-8",
        )
        (tmp_path / "core" / "automation").mkdir(parents=True)
        (
            tmp_path / "core" / "automation"
            / "autonomy_armed.py"
        ).write_text(
            "SHOPAI_AUTO_DISARM_COOLDOWN_HOURS = ''\n"
            "SHOPAI_AUTO_DISARM_COOLDOWN_X_HOURS = ''\n",
            encoding="utf-8",
        )
        (
            tmp_path / "core" / "automation"
            / "autonomy_doctor.py"
        ).write_text(
            "_cd_hours()  # no domain arg\n",
            encoding="utf-8",
        )
        r = run_pattern_be_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == (
                "doctor_passes_domain_to_cooldown"
            )
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBEReport().has_violations

    def test_with_violations(self):
        r = PatternBEReport()
        r.violations.append(PatternBEViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
