"""Tests for the Wave 2 #6 SLA tracker.

Covers:

* SLAThresholds / SLASample dataclass shape
* SLATracker.record → sample storage per subsystem
* get_report() aggregation — success rate, p95 latency, cost/call
* status classification: ok / degraded / breached / unknown
* threshold overrides per subsystem
* env-var loading via SLATracker.from_env
* rolling window cap
* MetricsCollector integration — get_sla_tracker / get_sla_report
* reset(), subsystems()
"""
from __future__ import annotations

import os

import pytest

from core.telemetry.metrics_collector import (
    MetricsCollector,
    SLASample,
    SLATracker,
    SLAThresholds,
)


# ---------------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------------


def test_sla_thresholds_defaults():
    t = SLAThresholds()
    assert t.min_success_rate == 0.95
    assert t.max_p95_latency_ms == 1000.0
    assert t.max_cost_per_call == 0.01


def test_sla_thresholds_none_means_disabled():
    t = SLAThresholds(min_success_rate=None)
    assert t.min_success_rate is None


def test_sla_sample_fields():
    s = SLASample(success=True, latency_ms=100.0, cost=0.001)
    assert s.success is True
    assert s.latency_ms == 100.0
    assert s.cost == 0.001
    assert s.ts > 0


# ---------------------------------------------------------------------------
# Record + report basic path
# ---------------------------------------------------------------------------


def test_empty_tracker_reports_unknown():
    tr = SLATracker()
    r = tr.get_report("brain")
    assert r["status"] == "unknown"
    assert r["samples"] == 0
    assert r["success_rate"] is None


def test_record_and_get_report_single_subsystem():
    tr = SLATracker()
    for _ in range(100):
        tr.record("brain", success=True, latency_ms=200.0, cost=0.001)
    r = tr.get_report("brain")
    assert r["subsystem"] == "brain"
    assert r["samples"] == 100
    assert r["success_rate"] == 1.0
    assert r["p95_latency_ms"] == 200.0
    assert r["mean_cost_per_call"] == pytest.approx(0.001)
    assert r["status"] == "ok"
    assert r["breaches"] == []


def test_record_negative_latency_raises():
    tr = SLATracker()
    with pytest.raises(ValueError):
        tr.record("x", success=True, latency_ms=-1.0)


def test_record_negative_cost_raises():
    tr = SLATracker()
    with pytest.raises(ValueError):
        tr.record("x", success=True, latency_ms=10, cost=-1.0)


# ---------------------------------------------------------------------------
# Breach detection
# ---------------------------------------------------------------------------


def test_success_rate_breach():
    tr = SLATracker()
    for _ in range(10):
        tr.record("brain", success=True, latency_ms=50.0)
    for _ in range(10):
        tr.record("brain", success=False, latency_ms=50.0)
    # 50% success rate — way below 0.95 target
    r = tr.get_report("brain")
    assert r["status"] == "breached"
    assert "success_rate" in r["breaches"]


def test_p95_latency_breach():
    tr = SLATracker()
    # 10 samples all well over the 1000ms target → p95 hits 5000
    for _ in range(10):
        tr.record("api", success=True, latency_ms=5_000.0)
    r = tr.get_report("api")
    assert r["status"] == "breached"
    assert "p95_latency_ms" in r["breaches"]
    assert r["p95_latency_ms"] == 5_000.0


def test_cost_breach():
    tr = SLATracker()
    for _ in range(20):
        tr.record("llm", success=True, latency_ms=100.0, cost=0.5)
    r = tr.get_report("llm")
    assert r["status"] == "breached"
    assert "mean_cost_per_call" in r["breaches"]


def test_multiple_breaches_listed():
    tr = SLATracker()
    for _ in range(10):
        tr.record("bad", success=False, latency_ms=9_999.0, cost=1.0)
    r = tr.get_report("bad")
    assert r["status"] == "breached"
    assert set(r["breaches"]) == {
        "success_rate", "p95_latency_ms", "mean_cost_per_call",
    }


def test_degraded_status_on_marginal_latency():
    tr = SLATracker(
        default_thresholds=SLAThresholds(
            min_success_rate=None,
            max_p95_latency_ms=1_000.0,
            max_cost_per_call=None,
        ),
    )
    # 950ms sits inside the 10% warning band but below the breach
    for _ in range(20):
        tr.record("x", success=True, latency_ms=950.0)
    r = tr.get_report("x")
    assert r["status"] == "degraded"
    assert "p95_latency_ms" in r["warnings"]
    assert r["breaches"] == []


# ---------------------------------------------------------------------------
# Threshold overrides + disabled dimensions
# ---------------------------------------------------------------------------


def test_set_thresholds_override():
    tr = SLATracker()
    tr.set_thresholds(
        "latency_sensitive",
        SLAThresholds(
            min_success_rate=None,
            max_p95_latency_ms=50.0,
            max_cost_per_call=None,
        ),
    )
    for _ in range(20):
        tr.record("latency_sensitive", success=False, latency_ms=200.0)
    r = tr.get_report("latency_sensitive")
    # success_rate is disabled → no breach from that dimension
    assert "success_rate" not in r["breaches"]
    assert "p95_latency_ms" in r["breaches"]


def test_disabled_threshold_never_breaches():
    tr = SLATracker(
        default_thresholds=SLAThresholds(
            min_success_rate=None,
            max_p95_latency_ms=None,
            max_cost_per_call=None,
        ),
    )
    for _ in range(20):
        tr.record("x", success=False, latency_ms=10_000.0, cost=100.0)
    r = tr.get_report("x")
    assert r["status"] == "ok"
    assert r["breaches"] == []


# ---------------------------------------------------------------------------
# Rolling window + reset
# ---------------------------------------------------------------------------


def test_window_size_caps_samples():
    tr = SLATracker(window_size=10)
    for i in range(100):
        tr.record("x", success=True, latency_ms=float(i))
    r = tr.get_report("x")
    assert r["samples"] == 10
    # Only the last 10 latencies (90..99) remain
    assert r["p95_latency_ms"] == 99.0


def test_window_size_zero_raises():
    with pytest.raises(ValueError):
        SLATracker(window_size=0)


def test_reset_one_subsystem():
    tr = SLATracker()
    tr.record("a", success=True, latency_ms=10.0)
    tr.record("b", success=True, latency_ms=10.0)
    tr.reset("a")
    assert "a" not in tr.subsystems()
    assert "b" in tr.subsystems()


def test_reset_all():
    tr = SLATracker()
    tr.record("a", success=True, latency_ms=10.0)
    tr.record("b", success=True, latency_ms=10.0)
    tr.reset()
    assert tr.subsystems() == []


# ---------------------------------------------------------------------------
# Multi-subsystem report
# ---------------------------------------------------------------------------


def test_get_report_all_subsystems():
    tr = SLATracker()
    tr.record("a", success=True, latency_ms=100.0)
    tr.record("b", success=True, latency_ms=200.0)
    report = tr.get_report()
    assert "subsystems" in report
    assert set(report["subsystems"].keys()) == {"a", "b"}
    assert report["total_subsystems"] == 2


def test_subsystems_sorted():
    tr = SLATracker()
    for name in ("zebra", "alpha", "mango"):
        tr.record(name, success=True, latency_ms=10.0)
    assert tr.subsystems() == ["alpha", "mango", "zebra"]


# ---------------------------------------------------------------------------
# Env loading
# ---------------------------------------------------------------------------


def test_from_env_uses_defaults_when_unset(monkeypatch):
    for k in (
        "SHOPAI_SLA_WINDOW_SIZE",
        "SHOPAI_SLA_MIN_SUCCESS_RATE",
        "SHOPAI_SLA_MAX_P95_LATENCY_MS",
        "SHOPAI_SLA_MAX_COST_PER_CALL",
    ):
        monkeypatch.delenv(k, raising=False)
    tr = SLATracker.from_env()
    assert tr._default.min_success_rate == 0.95
    assert tr._default.max_p95_latency_ms == 1000.0


def test_from_env_parses_values(monkeypatch):
    monkeypatch.setenv("SHOPAI_SLA_WINDOW_SIZE", "50")
    monkeypatch.setenv("SHOPAI_SLA_MIN_SUCCESS_RATE", "0.80")
    monkeypatch.setenv("SHOPAI_SLA_MAX_P95_LATENCY_MS", "500")
    monkeypatch.setenv("SHOPAI_SLA_MAX_COST_PER_CALL", "0.05")
    tr = SLATracker.from_env()
    assert tr._window_size == 50
    assert tr._default.min_success_rate == 0.80
    assert tr._default.max_p95_latency_ms == 500.0
    assert tr._default.max_cost_per_call == 0.05


def test_from_env_ignores_bad_values(monkeypatch):
    monkeypatch.setenv("SHOPAI_SLA_WINDOW_SIZE", "not-a-number")
    monkeypatch.setenv("SHOPAI_SLA_MIN_SUCCESS_RATE", "abc")
    tr = SLATracker.from_env()
    assert tr._window_size == 500  # fell back to default
    assert tr._default.min_success_rate == 0.95


# ---------------------------------------------------------------------------
# MetricsCollector integration
# ---------------------------------------------------------------------------


def test_metrics_collector_get_sla_tracker_is_singleton():
    mc = MetricsCollector()
    t1 = mc.get_sla_tracker()
    t2 = mc.get_sla_tracker()
    assert t1 is t2


def test_metrics_collector_get_sla_report_proxies_tracker():
    mc = MetricsCollector()
    # Reset to clean state since MetricsCollector is a process-wide
    # singleton
    mc.get_sla_tracker().reset()
    mc.get_sla_tracker().record(
        "brain", success=True, latency_ms=100.0,
    )
    report = mc.get_sla_report("brain")
    assert report["subsystem"] == "brain"
    assert report["samples"] == 1
    assert report["status"] == "ok"


def test_metrics_collector_report_all():
    mc = MetricsCollector()
    mc.get_sla_tracker().reset()
    mc.get_sla_tracker().record("a", success=True, latency_ms=10.0)
    mc.get_sla_tracker().record("b", success=True, latency_ms=10.0)
    report = mc.get_sla_report()
    assert "subsystems" in report
    assert set(report["subsystems"].keys()) >= {"a", "b"}
