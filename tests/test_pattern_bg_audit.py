"""Tests for engines._pattern_bg_audit (Wave 874)."""
from __future__ import annotations

from engines._pattern_bg_audit import (
    PatternBGReport,
    PatternBGViolation,
    _CLI_SURFACES,
    _file_references,
    run_pattern_bg_audit,
)


class TestLive:

    def test_live_branch_passes(self):
        r = run_pattern_bg_audit()
        assert not r.has_violations, [
            (v.invariant, v.reason) for v in r.violations
        ]

    def test_twelve_invariants_checked(self):
        r = run_pattern_bg_audit()
        # 6 CLI surfaces * 2 invariants (flag + plumb) = 12
        assert len(r.invariants_checked) == 12


class TestCatalogShape:

    def test_six_surfaces(self):
        assert len(_CLI_SURFACES) == 6

    def test_every_entry_is_3_tuple(self):
        for entry in _CLI_SURFACES:
            assert isinstance(entry, tuple)
            assert len(entry) == 3
            parser, fn, token = entry
            assert parser.endswith("_p")
            assert callable.__call__ is not None  # smoke
            assert token == "store_id="


class TestFileReferences:

    def test_present(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text("a\nb\n", encoding="utf-8")
        assert _file_references(f, "a", "b")

    def test_missing(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text("a only\n", encoding="utf-8")
        assert not _file_references(f, "a", "b")


class TestSyntheticDrift:

    def test_synthetic_no_plumb_anywhere(self, tmp_path):
        # cli.py never mentions store_id= -> every plumb
        # invariant fails (6 surfaces).
        (tmp_path / "cli.py").write_text(
            'autonomy_status_p.add_argument("--store")\n'
            "get_autonomy_status()\n"
            'autonomy_doctor_p.add_argument("--store")\n'
            "run_autonomy_doctor()\n"
            'autonomy_kpi_p.add_argument("--store")\n'
            "compute_fire_kpis()\n"
            'autonomy_alerts_p.add_argument("--store")\n'
            "compute_fire_alerts()\n"
            'autonomy_fire_status_p.add_argument("--store")\n'
            "recent_substrate_fires()\n"
            'autonomy_fire_trend_p.add_argument("--store")\n'
            "compute_fire_trend()\n",
            encoding="utf-8",
        )
        r = run_pattern_bg_audit(repo_root=tmp_path)
        plumbs = [
            v for v in r.violations
            if v.invariant.endswith("_plumbs_store_id")
        ]
        # All 6 plumb invariants fail
        assert len(plumbs) == 6

    def test_synthetic_missing_status_flag(self, tmp_path):
        (tmp_path / "cli.py").write_text(
            # status missing --store
            "get_autonomy_status(store_id=...)\n"
            'autonomy_doctor_p.add_argument("--store")\n'
            "run_autonomy_doctor(store_id=...)\n"
            'autonomy_kpi_p.add_argument("--store")\n'
            "compute_fire_kpis(store_id=...)\n"
            'autonomy_alerts_p.add_argument("--store")\n'
            "compute_fire_alerts(store_id=...)\n"
            'autonomy_fire_status_p.add_argument("--store")\n'
            "recent_substrate_fires(store_id=...)\n"
            'autonomy_fire_trend_p.add_argument("--store")\n'
            "compute_fire_trend(store_id=...)\n",
            encoding="utf-8",
        )
        r = run_pattern_bg_audit(repo_root=tmp_path)
        bad = [
            v for v in r.violations
            if v.invariant == "autonomy_status_p_has_store_flag"
        ]
        assert bad


class TestReportDataclass:

    def test_empty_no_violations(self):
        assert not PatternBGReport().has_violations

    def test_with_violations(self):
        r = PatternBGReport()
        r.violations.append(PatternBGViolation(
            invariant="x", reason="y",
        ))
        assert r.has_violations
