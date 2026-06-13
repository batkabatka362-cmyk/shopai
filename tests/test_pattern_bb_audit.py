"""Tests for engines._pattern_bb_audit (Wave 857)."""
from __future__ import annotations

from engines._pattern_bb_audit import (
    PatternBBReport,
    PatternBBViolation,
    _file_references,
    run_pattern_bb_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bb_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_six_invariants_checked(self):
        r = run_pattern_bb_audit()
        # 6 invariants per the module docstring
        # (record_alerts + consecutive_critical_days +
        # maybe_auto_disarm callables + 3 cross-module
        # references)
        assert len(r.invariants_checked) >= 6


class TestFileReferences:

    def test_all_symbols_present(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text(
            "from y import a, b, c\n", encoding="utf-8",
        )
        assert _file_references(f, "a", "b", "c")

    def test_any_symbol_missing(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text("from y import a\n", encoding="utf-8")
        assert not _file_references(f, "a", "b")

    def test_unreadable_file_returns_false(self, tmp_path):
        f = tmp_path / "nope.py"
        assert not _file_references(f, "a")


class TestSyntheticDrift:

    def test_synthetic_broken_alerter(self, tmp_path):
        # Build a tree with empty/broken substrate_fire_alerts.py
        # -- Pattern BB should flag the missing record_alerts ref.
        (tmp_path / "core" / "automation").mkdir(parents=True)
        # Empty alerts file
        (
            tmp_path / "core" / "automation"
            / "substrate_fire_alerts.py"
        ).write_text("# empty\n", encoding="utf-8")
        # Build auto_disarm + alert_history skeletons so the
        # other invariants don't trip.
        (
            tmp_path / "core" / "automation"
            / "substrate_fire_auto_disarm.py"
        ).write_text(
            "from x import list_armed\n"
            "from y import consecutive_critical_days\n",
            encoding="utf-8",
        )
        (tmp_path / "cli.py").write_text(
            "# referenced: maybe_auto_disarm\n",
            encoding="utf-8",
        )
        r = run_pattern_bb_audit(repo_root=tmp_path)
        assert r.has_violations
        broken = [
            v for v in r.violations
            if v.invariant == "alerts_records_to_history"
        ]
        assert broken

    def test_synthetic_missing_cycle_hook(self, tmp_path):
        # All other files reference correctly, but cli.py
        # doesn't reference maybe_auto_disarm.
        (tmp_path / "core" / "automation").mkdir(parents=True)
        (
            tmp_path / "core" / "automation"
            / "substrate_fire_alerts.py"
        ).write_text(
            "record_alerts(...)\n", encoding="utf-8",
        )
        (
            tmp_path / "core" / "automation"
            / "substrate_fire_auto_disarm.py"
        ).write_text(
            "from x import list_armed\n"
            "from y import consecutive_critical_days\n",
            encoding="utf-8",
        )
        (tmp_path / "cli.py").write_text(
            "# no bridge ref\n", encoding="utf-8",
        )
        r = run_pattern_bb_audit(repo_root=tmp_path)
        broken = [
            v for v in r.violations
            if v.invariant == "cycle_hook_invokes_bridge"
        ]
        assert broken


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBBReport().has_violations

    def test_with_violations(self):
        r = PatternBBReport()
        r.violations.append(PatternBBViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
