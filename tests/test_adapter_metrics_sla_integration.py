"""Integration tests: adapter MetricsCollector.record feeds SLATracker
(Wave 3 #4).

Wave 2 #6 shipped SLATracker as a sibling of the telemetry
MetricsCollector but the adapter-side metrics recorder (which is
what every real adapter call actually writes through via
core/adapters/router.py) never fed it. Wave 3 #4 plumbs every
``AdapterMetrics.record`` call into the shared SLATracker so
operators get per-adapter rolling health out of the box.

These tests drive the real call path — create a collector, run
some synthetic record() calls, then query the telemetry
SLATracker directly to confirm the samples arrived with the
right success / latency / cost values.
"""
from __future__ import annotations

import pytest

from core.adapters.metrics import AdapterMetricsCollector
from core.telemetry.metrics_collector import (
    MetricsCollector as TelemetryMetricsCollector,
    SLAThresholds,
    SLATracker,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_sla_tracker():
    """Replace the telemetry singleton's SLA tracker with a fresh
    instance per test so samples from other tests don't bleed
    through (the telemetry MetricsCollector is a process-wide
    singleton by design).
    """
    tel = TelemetryMetricsCollector()
    original = tel._sla
    tel._sla = SLATracker(window_size=100)
    yield tel._sla
    tel._sla = original


@pytest.fixture
def adapter_collector() -> AdapterMetricsCollector:
    return AdapterMetricsCollector()


# ---------------------------------------------------------------------------
# Basic forwarding
# ---------------------------------------------------------------------------


def test_single_record_lands_in_sla_tracker(
    adapter_collector, _fresh_sla_tracker,
):
    adapter_collector.record(
        "openai",
        success=True,
        latency_ms=120.0,
        cost_usd=0.0012,
    )
    report = _fresh_sla_tracker.get_report("openai")
    assert report["samples"] == 1
    assert report["success_rate"] == 1.0
    assert report["p95_latency_ms"] == pytest.approx(120.0)


def test_multiple_records_build_rolling_window(
    adapter_collector, _fresh_sla_tracker,
):
    for _ in range(10):
        adapter_collector.record(
            "anthropic", success=True, latency_ms=50.0, cost_usd=0.001,
        )
    report = _fresh_sla_tracker.get_report("anthropic")
    assert report["samples"] == 10
    assert report["success_rate"] == 1.0


def test_failure_samples_lower_success_rate(
    adapter_collector, _fresh_sla_tracker,
):
    for _ in range(7):
        adapter_collector.record("gemini", success=True, latency_ms=200.0)
    for _ in range(3):
        adapter_collector.record("gemini", success=False, latency_ms=200.0,
                                  error="rate limit")
    report = _fresh_sla_tracker.get_report("gemini")
    assert report["samples"] == 10
    assert report["success_rate"] == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# Per-adapter isolation
# ---------------------------------------------------------------------------


def test_samples_segregated_by_adapter_name(
    adapter_collector, _fresh_sla_tracker,
):
    adapter_collector.record("openai", success=True, latency_ms=100.0)
    adapter_collector.record("anthropic", success=False, latency_ms=500.0)
    adapter_collector.record("anthropic", success=False, latency_ms=500.0)

    openai_report = _fresh_sla_tracker.get_report("openai")
    anthropic_report = _fresh_sla_tracker.get_report("anthropic")

    assert openai_report["samples"] == 1
    assert openai_report["success_rate"] == 1.0
    assert anthropic_report["samples"] == 2
    assert anthropic_report["success_rate"] == 0.0


# ---------------------------------------------------------------------------
# Cost propagation
# ---------------------------------------------------------------------------


def test_cost_per_call_forwarded(adapter_collector, _fresh_sla_tracker):
    adapter_collector.record(
        "deepseek", success=True, latency_ms=80.0, cost_usd=0.005,
    )
    report = _fresh_sla_tracker.get_report("deepseek")
    assert report["mean_cost_per_call"] == pytest.approx(0.005)


def test_zero_cost_is_still_recorded(
    adapter_collector, _fresh_sla_tracker,
):
    adapter_collector.record(
        "local-model", success=True, latency_ms=10.0,
    )
    report = _fresh_sla_tracker.get_report("local-model")
    assert report["samples"] == 1
    assert report["mean_cost_per_call"] == 0.0


# ---------------------------------------------------------------------------
# SLA status rollup
# ---------------------------------------------------------------------------


def test_latency_breach_flagged(adapter_collector, _fresh_sla_tracker):
    # Override the threshold for this adapter before feeding samples
    _fresh_sla_tracker.set_thresholds(
        "slow-api",
        SLAThresholds(min_success_rate=0.0, max_p95_latency_ms=100.0),
    )
    for _ in range(10):
        adapter_collector.record(
            "slow-api", success=True, latency_ms=5_000.0,
        )
    report = _fresh_sla_tracker.get_report("slow-api")
    assert report["status"] == "breached"
    assert "p95_latency_ms" in report["breaches"]


def test_healthy_adapter_reports_ok(
    adapter_collector, _fresh_sla_tracker,
):
    _fresh_sla_tracker.set_thresholds(
        "fast-api",
        SLAThresholds(min_success_rate=0.90, max_p95_latency_ms=200.0),
    )
    for _ in range(20):
        adapter_collector.record(
            "fast-api", success=True, latency_ms=50.0, cost_usd=0.0,
        )
    report = _fresh_sla_tracker.get_report("fast-api")
    assert report["status"] == "ok"
    assert report["breaches"] == []


# ---------------------------------------------------------------------------
# get_sla_report forwarder
# ---------------------------------------------------------------------------


def test_collector_get_sla_report_returns_same_shape(
    adapter_collector, _fresh_sla_tracker,
):
    adapter_collector.record("x", success=True, latency_ms=10.0)
    via_collector = adapter_collector.get_sla_report("x")
    via_tracker = _fresh_sla_tracker.get_report("x")
    assert via_collector == via_tracker


def test_collector_get_sla_report_all_adapters(
    adapter_collector, _fresh_sla_tracker,
):
    adapter_collector.record("a", success=True, latency_ms=10.0)
    adapter_collector.record("b", success=True, latency_ms=20.0)
    report = adapter_collector.get_sla_report()
    # All-subsystem report is wrapped: {"subsystems": {...}, "total_subsystems": N}
    subsystems = report["subsystems"]
    assert "a" in subsystems
    assert "b" in subsystems
    assert report["total_subsystems"] == 2


# ---------------------------------------------------------------------------
# Fail-safe: SLA feed crash doesn't break the real record() path
# ---------------------------------------------------------------------------


def test_sla_tracker_crash_does_not_break_adapter_metrics(
    adapter_collector, monkeypatch,
):
    def _boom(*args, **kwargs):
        raise RuntimeError("sla down")

    # Break every SLATracker.record call so the feed path crashes
    monkeypatch.setattr(SLATracker, "record", _boom)
    # record() must still land the adapter stats without raising
    adapter_collector.record("openai", success=True, latency_ms=100.0)
    stats = adapter_collector.stats_for("openai")
    assert stats is not None
    assert stats["calls_total"] == 1


def test_sla_report_returns_empty_dict_when_tracker_crashes(
    adapter_collector, monkeypatch,
):
    # Break the telemetry collector's tracker construction so the
    # get_sla_report path fails and must fall back to {}
    def _boom(self):
        raise RuntimeError("tel down")

    monkeypatch.setattr(
        TelemetryMetricsCollector, "get_sla_tracker", _boom,
    )
    assert adapter_collector.get_sla_report("anything") == {}


# ---------------------------------------------------------------------------
# Existing adapter stats path untouched
# ---------------------------------------------------------------------------


def test_existing_adapter_stats_still_work_alongside_sla(
    adapter_collector, _fresh_sla_tracker,
):
    adapter_collector.record(
        "openai", success=True, latency_ms=150.0, cost_usd=0.002,
        tokens_in=100, tokens_out=50,
    )
    stats = adapter_collector.stats_for("openai")
    assert stats["calls_total"] == 1
    assert stats["calls_success"] == 1
    assert stats["cost_usd_total"] == pytest.approx(0.002)
    assert stats["tokens_in_total"] == 100
    assert stats["tokens_out_total"] == 50
    # And SLA tracker received the same call
    sla = _fresh_sla_tracker.get_report("openai")
    assert sla["samples"] == 1
