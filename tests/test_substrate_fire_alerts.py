"""Tests for core.automation.substrate_fire_alerts (W849)."""
from __future__ import annotations

from unittest.mock import patch

from core.automation.substrate_fire_alerts import (
    FireAlert,
    FireAlertsReport,
    compute_fire_alerts,
    _evaluate,
    _max_errors,
    _min_sample,
    _min_success_rate,
)
from core.automation.substrate_fire_kpi import (
    DomainFireKPI,
    FireKPIReport,
)


class TestEvaluate:

    def test_below_min_sample_no_alert(self):
        k = DomainFireKPI(domain="x", fired=0, errors=1)
        alerts = _evaluate(k, min_rate=0.5, max_err=3, min_sample=3)
        assert alerts == []

    def test_low_success_rate_warn(self):
        # 2 fired / 6 actionable = 33% < 50%, sample=6
        k = DomainFireKPI(domain="x", fired=2, errors=4)
        alerts = _evaluate(k, min_rate=0.5, max_err=10, min_sample=3)
        assert len(alerts) == 1
        assert alerts[0].kind == "low_success_rate"
        assert alerts[0].severity == "warn"

    def test_critical_when_half_of_threshold(self):
        # 1 fired / 10 = 10% < (50% / 2 = 25%) -> critical
        k = DomainFireKPI(domain="x", fired=1, errors=9)
        alerts = _evaluate(k, min_rate=0.5, max_err=100, min_sample=3)
        assert alerts[0].severity == "critical"

    def test_high_error_count(self):
        k = DomainFireKPI(domain="x", fired=10, errors=5)
        alerts = _evaluate(k, min_rate=0.0, max_err=3, min_sample=3)
        assert len(alerts) == 1
        assert alerts[0].kind == "high_error_count"

    def test_both_kinds_can_fire_together(self):
        # 0 fired / 10 errors = 0% success + errors > 3
        k = DomainFireKPI(domain="x", fired=0, errors=10)
        alerts = _evaluate(k, min_rate=0.5, max_err=3, min_sample=3)
        assert len(alerts) == 2
        kinds = sorted(a.kind for a in alerts)
        assert kinds == [
            "high_error_count", "low_success_rate",
        ]

    def test_clean_domain_no_alerts(self):
        k = DomainFireKPI(domain="x", fired=10, errors=0)
        alerts = _evaluate(k, min_rate=0.5, max_err=3, min_sample=3)
        assert alerts == []


class TestComputeFireAlerts:

    def test_empty_report_no_alerts(self):
        with patch(
            "core.automation.substrate_fire_alerts."
            "compute_fire_kpis",
            return_value=FireKPIReport(),
        ):
            r = compute_fire_alerts()
        assert not r.has_alerts
        assert r.domains_evaluated == 0

    def test_mixed_kpis_flag_only_bad(self):
        kpis = FireKPIReport()
        kpis.per_domain = [
            DomainFireKPI(
                domain="healthy", fired=10, errors=0,
            ),
            DomainFireKPI(
                domain="bad", fired=1, errors=5,
            ),
        ]
        with patch(
            "core.automation.substrate_fire_alerts."
            "compute_fire_kpis",
            return_value=kpis,
        ):
            r = compute_fire_alerts()
        assert r.domains_evaluated == 2
        domains = {a.domain for a in r.alerts}
        assert domains == {"bad"}

    def test_window_and_store_forwarded(self):
        with patch(
            "core.automation.substrate_fire_alerts."
            "compute_fire_kpis",
            return_value=FireKPIReport(),
        ) as mocked:
            compute_fire_alerts(
                window_hours=24.0, store_id="store-1",
            )
        mocked.assert_called_once_with(
            window_hours=24.0, store_id="store-1",
        )

    def test_config_recorded_in_report(self):
        with patch(
            "core.automation.substrate_fire_alerts."
            "compute_fire_kpis",
            return_value=FireKPIReport(),
        ):
            r = compute_fire_alerts()
        assert "min_success_rate" in r.config
        assert "max_errors" in r.config
        assert "min_sample" in r.config


class TestEnvKnobs:

    def test_min_rate_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTONOMY_ALERT_MIN_SUCCESS_RATE",
            raising=False,
        )
        assert _min_success_rate() == 0.50

    def test_min_rate_clamped_0_to_1(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_AUTONOMY_ALERT_MIN_SUCCESS_RATE", "2.0",
        )
        assert _min_success_rate() == 1.0

    def test_max_errors_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTONOMY_ALERT_MAX_ERRORS", raising=False,
        )
        assert _max_errors() == 3

    def test_min_sample_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTONOMY_ALERT_MIN_SAMPLE", raising=False,
        )
        assert _min_sample() == 3


class TestReportDataclass:

    def test_empty_aggregates_zero(self):
        r = FireAlertsReport()
        assert not r.has_alerts
        assert r.critical_count == 0
        assert r.warn_count == 0

    def test_mixed_severity_aggregates(self):
        r = FireAlertsReport()
        r.alerts.extend([
            FireAlert(
                domain="x", kind="low_success_rate",
                severity="critical", reason="",
            ),
            FireAlert(
                domain="y", kind="high_error_count",
                severity="warn", reason="",
            ),
            FireAlert(
                domain="z", kind="low_success_rate",
                severity="critical", reason="",
            ),
        ])
        assert r.has_alerts
        assert r.critical_count == 2
        assert r.warn_count == 1
