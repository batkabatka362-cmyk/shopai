"""Tests for core.automation.autonomy_export (Wave 369-374)."""
from __future__ import annotations

from core.automation.autonomy_export import (
    AutonomyExport,
    _audits_section,
    _bench_section,
    _doctor_section,
    _env_section,
    _events_section,
    _safe_dataclass_asdict,
    _smoke_section,
    _status_section,
    run_autonomy_export,
)


class TestSafeDataclassAsdict:

    def test_real_dataclass(self):
        from core.automation.autonomy_status import DomainSummary
        d = DomainSummary(name="x")
        result = _safe_dataclass_asdict(d)
        assert result["name"] == "x"

    def test_non_dataclass_returns_empty(self):
        result = _safe_dataclass_asdict(42)
        assert result == {}


class TestStatusSection:

    def test_returns_required_fields(self):
        s = _status_section(24.0, None)
        assert "overall_verdict" in s
        assert "domains" in s
        assert isinstance(s["domains"], list)
        assert len(s["domains"]) >= 7


class TestDoctorSection:

    def test_returns_required_fields(self):
        d = _doctor_section(24.0, None)
        assert "overall_cls" in d
        assert "ok" in d
        assert "warn" in d
        assert "fail" in d
        assert len(d["domains"]) >= 7


class TestSmokeSection:

    def test_returns_required_fields(self):
        s = _smoke_section()
        assert "overall_cls" in s
        assert "domains" in s
        assert len(s["domains"]) >= 7


class TestBenchSection:

    def test_returns_required_fields(self):
        b = _bench_section(runs=1)
        assert "runs_per_domain" in b
        assert "total_ms" in b
        assert "domains" in b
        assert len(b["domains"]) >= 7


class TestEnvSection:

    def test_returns_required_fields(self):
        e = _env_section()
        # W937: knob count grows over time; subset semantics
        assert e["total_knobs"] >= 43
        assert "knobs" in e
        assert isinstance(e["knobs"], list)


class TestEventsSection:

    def test_returns_list(self):
        events = _events_section(24.0, None, 50)
        assert isinstance(events, list)
        # idle branch -- expect 0 events
        assert len(events) == 0


class TestAuditsSection:

    def test_returns_dict_per_audit(self):
        a = _audits_section()
        # 19 audits in the catalog (W through AR)
        assert len(a) >= 18
        # Each has at least an "ok" boolean
        for name, info in a.items():
            assert "ok" in info, name


class TestRunAutonomyExport:

    def test_returns_autonomy_export(self):
        e = run_autonomy_export(
            skip_bench=True, skip_audits=True,
        )
        assert isinstance(e, AutonomyExport)

    def test_meta_contains_timestamp(self):
        e = run_autonomy_export(
            skip_bench=True, skip_audits=True,
        )
        assert "generated_at" in e.meta
        assert "T" in e.meta["generated_at"]  # ISO-ish

    def test_skip_bench_omits_bench(self):
        e = run_autonomy_export(
            skip_bench=True, skip_audits=True,
        )
        # When skipped, bench is empty dict (the default)
        assert e.bench == {}

    def test_skip_audits_omits_audits(self):
        e = run_autonomy_export(
            skip_bench=True, skip_audits=True,
        )
        assert e.audits == {}

    def test_full_export_includes_all(self):
        e = run_autonomy_export(
            bench_runs=1, events_limit=10,
        )
        assert e.status
        assert e.doctor
        assert e.smoke
        assert e.bench
        assert e.env
        assert e.audits

    def test_store_id_preserved(self):
        e = run_autonomy_export(
            store_id="store-xyz",
            skip_bench=True, skip_audits=True,
        )
        assert e.meta["store_id"] == "store-xyz"


class TestExportDataclassDefaults:

    def test_empty_export(self):
        e = AutonomyExport()
        assert e.meta == {}
        assert e.status == {}
        assert e.recent_events == []
