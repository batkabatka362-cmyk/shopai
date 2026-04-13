"""Wave 4 #3: dashboard_api surfaces the adapter SLA report.

Wave 3 #4 wired MetricsCollector.record into the telemetry
SLATracker, and added a get_sla_report forwarder on the adapter
collector. But no HTTP endpoint exposed it, so operators had no
way to see per-adapter rolling health without pulling a Python
REPL open.

Wave 4 #3 adds:

* ``GET /api/metrics/adapters`` — full SLA report
* ``/api/status`` now carries an ``adapters_sla`` summary

Both must fail soft: an SLA feed crash or a telemetry import
error can never crash the dashboard server.
"""
from __future__ import annotations

from typing import Any

import pytest

from api.dashboard_api import DashboardAPIHandler
from core.adapters.metrics import get_metrics, reset_metrics
from core.telemetry.metrics_collector import (
    MetricsCollector as TelemetryMetricsCollector,
    SLAThresholds,
    SLATracker,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_metrics():
    """Reset both the adapter collector singleton and the telemetry
    SLATracker so tests in this file don't bleed state into each
    other."""
    reset_metrics()
    tel = TelemetryMetricsCollector()
    original = tel._sla
    tel._sla = SLATracker(window_size=100)
    yield
    tel._sla = original
    reset_metrics()


# ---------------------------------------------------------------------------
# /api/metrics/adapters — full report
# ---------------------------------------------------------------------------


def test_metrics_adapters_empty_when_no_adapter_calls():
    out = DashboardAPIHandler._get_adapter_metrics()
    assert "report" in out
    assert "summary" in out
    assert "timestamp" in out
    assert out["summary"]["total"] == 0


def test_metrics_adapters_reflects_recorded_calls():
    col = get_metrics()
    for _ in range(10):
        col.record("openai", success=True, latency_ms=120.0, cost_usd=0.001)
    for _ in range(3):
        col.record("anthropic", success=False, latency_ms=500.0)

    out = DashboardAPIHandler._get_adapter_metrics()
    summary = out["summary"]
    assert summary["total"] == 2
    # openai is healthy, anthropic failed every call
    assert "anthropic" in summary["breaching"] or summary["degraded"] >= 1


def test_metrics_adapters_reports_breach_when_threshold_violated():
    col = get_metrics()
    # Force a tight latency threshold for slow-api
    tel = TelemetryMetricsCollector()
    tel.get_sla_tracker().set_thresholds(
        "slow-api",
        SLAThresholds(min_success_rate=0.0, max_p95_latency_ms=100.0),
    )
    for _ in range(10):
        col.record("slow-api", success=True, latency_ms=5_000.0)
    out = DashboardAPIHandler._get_adapter_metrics()
    assert "slow-api" in out["summary"]["breaching"]
    assert out["summary"]["breached"] >= 1


# ---------------------------------------------------------------------------
# /api/status — adapter SLA summary
# ---------------------------------------------------------------------------


def test_status_carries_adapter_sla_summary_key():
    status = DashboardAPIHandler._get_status()
    assert "adapters_sla" in status
    assert isinstance(status["adapters_sla"], dict)
    assert set(status["adapters_sla"].keys()) >= {
        "total", "ok", "degraded", "breached", "breaching",
    }


def test_status_summary_counts_live_adapters():
    col = get_metrics()
    for _ in range(5):
        col.record("gemini", success=True, latency_ms=50.0)
    status = DashboardAPIHandler._get_status()
    summary = status["adapters_sla"]
    assert summary["total"] >= 1


# ---------------------------------------------------------------------------
# Fail-safe
# ---------------------------------------------------------------------------


def test_metrics_adapters_degrades_when_telemetry_explodes(monkeypatch):
    def _boom(self):
        raise RuntimeError("telemetry down")

    monkeypatch.setattr(
        TelemetryMetricsCollector, "get_sla_tracker", _boom,
    )
    # Collector's get_sla_report returns {} on failure — endpoint
    # returns an empty-summary payload, NOT an error.
    out = DashboardAPIHandler._get_adapter_metrics()
    assert out["summary"]["total"] == 0
    assert "report" in out


def test_status_absorbs_adapter_sla_failure(monkeypatch):
    from core.adapters import metrics as metrics_mod

    def _boom():
        raise RuntimeError("metrics down")

    monkeypatch.setattr(metrics_mod, "get_metrics", _boom)
    # Should still return a dict with core fields, just without
    # adapters_sla
    status = DashboardAPIHandler._get_status()
    assert status["status"] == "running"
    assert "adapters_sla" not in status


# ---------------------------------------------------------------------------
# _summarise_sla — pure helper
# ---------------------------------------------------------------------------


def test_summarise_sla_handles_plain_and_wrapped_shapes():
    plain = {
        "a": {"status": "ok"},
        "b": {"status": "degraded"},
        "c": {"status": "breached"},
    }
    s = DashboardAPIHandler._summarise_sla(plain)
    assert s == {
        "total": 3, "ok": 1, "degraded": 1, "breached": 1,
        "breaching": ["c"],
    }

    wrapped = {"subsystems": plain, "total_subsystems": 3}
    s2 = DashboardAPIHandler._summarise_sla(wrapped)
    assert s2["total"] == 3
    assert s2["breaching"] == ["c"]


def test_summarise_sla_handles_empty_and_garbage():
    assert DashboardAPIHandler._summarise_sla({})["total"] == 0
    assert DashboardAPIHandler._summarise_sla(None)["total"] == 0  # type: ignore[arg-type]
    assert DashboardAPIHandler._summarise_sla(
        {"subsystems": "not a dict"},
    )["total"] == 0
