"""Dashboard SLA endpoint — Option S phase 2.

Tests the ``_collect_sla_snapshot`` rollup and the ``/api/sla``
handler wiring.
"""
from __future__ import annotations

import pytest

from core.adapters.sla import SLABudget, SLAMonitor
from dashboard import app as dash
from dashboard.app import (
    DashboardAPIHandler,
    _collect_sla_snapshot,
    _reset_sla_monitor,
)


def _handler() -> DashboardAPIHandler:
    return object.__new__(DashboardAPIHandler)


@pytest.fixture(autouse=True)
def _reset_between_tests():
    _reset_sla_monitor()
    yield
    _reset_sla_monitor()


class TestCollectSLASnapshot:
    def test_empty_metrics_returns_empty_rows(self, monkeypatch):
        fake_metrics = type("M", (), {"snapshot": lambda self: {}})()
        monkeypatch.setattr(
            "core.adapters.metrics.get_metrics", lambda: fake_metrics,
        )
        monkeypatch.setattr(
            dash, "_get_sla_monitor", lambda: SLAMonitor(budgets={}),
        )
        snap = _collect_sla_snapshot()
        assert snap["rows"] == []
        assert snap["totals"] == {"breach": 0, "warn": 0, "ok": 0}

    def test_evaluates_against_budgets(self, monkeypatch):
        fake_metrics = type("M", (), {"snapshot": lambda self: {
            "fast": {
                "calls_total": 20, "latency_p50_ms": 50,
                "latency_p95_ms": 100, "latency_p99_ms": 150,
                "success_rate": 1.0,
            },
            "slow": {
                "calls_total": 20, "latency_p50_ms": 200,
                "latency_p95_ms": 3000, "latency_p99_ms": 5000,
                "success_rate": 1.0,
            },
        }})()
        monkeypatch.setattr(
            "core.adapters.metrics.get_metrics", lambda: fake_metrics,
        )
        monkeypatch.setattr(dash, "_get_sla_monitor", lambda: SLAMonitor(budgets={
            "fast": SLABudget(max_p95_ms=1000, min_samples=3),
            "slow": SLABudget(max_p95_ms=1000, min_samples=3),
        }))
        snap = _collect_sla_snapshot()
        assert snap["totals"]["breach"] == 1
        assert snap["totals"]["ok"] == 1
        # breach rows sort first
        assert snap["rows"][0]["adapter"] == "slow"
        assert snap["rows"][0]["grade"] == "breach"
        assert snap["rows"][1]["adapter"] == "fast"
        assert snap["rows"][1]["grade"] == "ok"


class TestSLAEndpoint:
    def test_api_sla_wraps_snapshot(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)
        monkeypatch.setattr(
            dash, "_collect_sla_snapshot",
            lambda: {
                "timestamp": 1.0,
                "totals": {"breach": 0, "warn": 1, "ok": 2},
                "rows": [{"adapter": "x", "grade": "ok"}],
            },
        )
        h._api_sla()
        assert captured["status"] == 200
        assert captured["payload"]["totals"]["warn"] == 1

    def test_api_sla_handles_collector_failure(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)

        def _boom():
            raise RuntimeError("metrics gone")

        monkeypatch.setattr(dash, "_collect_sla_snapshot", _boom)
        h._api_sla()
        assert captured["status"] == 200
        assert captured["payload"]["totals"] == {"breach": 0, "warn": 0, "ok": 0}
        assert "error" in captured["payload"]


class TestLazyMonitor:
    def test_monitor_is_singleton(self):
        from dashboard.app import _get_sla_monitor
        m1 = _get_sla_monitor()
        m2 = _get_sla_monitor()
        assert m1 is m2

    def test_reset_forces_new_instance(self):
        from dashboard.app import _get_sla_monitor
        m1 = _get_sla_monitor()
        _reset_sla_monitor()
        m2 = _get_sla_monitor()
        assert m1 is not m2
