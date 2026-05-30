"""Tests for core.automation.substrate_fire_kpi (Wave 847)."""
from __future__ import annotations

from unittest.mock import patch

from core.automation.substrate_fire_kpi import (
    DomainFireKPI,
    FireKPIReport,
    compute_fire_kpis,
)


class TestDomainFireKPI:

    def test_defaults_success_vacuous(self):
        k = DomainFireKPI(domain="x")
        # Nothing happened -> vacuously successful
        assert k.success_rate == 1.0

    def test_success_rate_excludes_dry_run(self):
        k = DomainFireKPI(
            domain="x",
            fired=3, errors=1, dry_run=10,
        )
        # 3 / (3+1) = 0.75 -- dry_run not counted
        assert k.success_rate == 0.75

    def test_success_rate_all_errors(self):
        k = DomainFireKPI(
            domain="x", fired=0, errors=5,
        )
        assert k.success_rate == 0.0

    def test_success_rate_all_fired(self):
        k = DomainFireKPI(
            domain="x", fired=10, errors=0,
        )
        assert k.success_rate == 1.0


class TestComputeFireKPIs:

    def test_empty_log_empty_report(self):
        with patch(
            "core.automation.substrate_fire_kpi."
            "recent_substrate_fires",
            return_value=[],
        ):
            r = compute_fire_kpis()
        assert r.per_domain == []

    def test_aggregates_by_domain(self):
        rows = [
            {
                "domain": "shipping_alert",
                "invoked": True,
                "reason": "fired",
                "duration_ms": 100.0,
            },
            {
                "domain": "shipping_alert",
                "invoked": True,
                "reason": "fired",
                "duration_ms": 200.0,
            },
            {
                "domain": "shipping_alert",
                "invoked": False,
                "reason": "dry_run",
                "duration_ms": 0.0,
            },
            {
                "domain": "catalog_quality",
                "invoked": False,
                "reason": "applier_error",
            },
        ]
        with patch(
            "core.automation.substrate_fire_kpi."
            "recent_substrate_fires",
            return_value=rows,
        ):
            r = compute_fire_kpis()
        assert len(r.per_domain) == 2
        sa = r.get("shipping_alert")
        assert sa is not None
        assert sa.total_outcomes == 3
        assert sa.fired == 2
        assert sa.dry_run == 1
        assert sa.errors == 0
        assert sa.avg_duration_ms == 150.0
        assert sa.success_rate == 1.0
        cq = r.get("catalog_quality")
        assert cq is not None
        assert cq.errors == 1
        assert cq.fired == 0
        assert cq.success_rate == 0.0

    def test_window_and_store_forwarded(self):
        with patch(
            "core.automation.substrate_fire_kpi."
            "recent_substrate_fires",
            return_value=[],
        ) as mocked:
            compute_fire_kpis(
                window_hours=24.0, store_id="store-7",
            )
        mocked.assert_called_once_with(
            window_hours=24.0, store_id="store-7",
        )

    def test_skips_rows_without_domain(self):
        rows = [
            {"invoked": True, "reason": "fired"},
            {"domain": "", "invoked": True, "reason": "fired"},
            {
                "domain": "shipping_alert",
                "invoked": True,
                "reason": "fired",
                "duration_ms": 50.0,
            },
        ]
        with patch(
            "core.automation.substrate_fire_kpi."
            "recent_substrate_fires",
            return_value=rows,
        ):
            r = compute_fire_kpis()
        assert len(r.per_domain) == 1
        assert r.per_domain[0].domain == "shipping_alert"


class TestFireKPIReport:

    def test_get_missing_domain_returns_none(self):
        r = FireKPIReport()
        assert r.get("nope") is None

    def test_get_existing_domain(self):
        r = FireKPIReport()
        k = DomainFireKPI(domain="x", fired=1)
        r.per_domain.append(k)
        assert r.get("x") is k
