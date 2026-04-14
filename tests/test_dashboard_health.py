"""Dashboard health-score endpoint — Option W phase 2.

Tests the ``_collect_health_snapshot`` rollup and the ``/api/health``
handler wiring.
"""
from __future__ import annotations

import pytest

from dashboard import app as dash
from dashboard.app import (
    DashboardAPIHandler,
    _collect_health_snapshot,
)


def _handler() -> DashboardAPIHandler:
    return object.__new__(DashboardAPIHandler)


class TestCollectHealthSnapshot:
    def test_empty_inputs_empty_rows(self, monkeypatch):
        monkeypatch.setattr(
            dash, "_collect_sla_snapshot",
            lambda: {"rows": [], "totals": {}, "timestamp": 0.0},
        )
        monkeypatch.setattr(
            dash, "_collect_retries_snapshot",
            lambda: {"breakers": [], "per_adapter": [], "totals": {}},
        )
        monkeypatch.setattr(
            dash, "_collect_ratelimit_snapshot",
            lambda: {"rows": [], "totals": {}, "timestamp": 0.0},
        )
        snap = _collect_health_snapshot()
        assert snap["rows"] == []
        # All grade buckets must be present even when empty so the UI
        # can index into them blindly.
        assert set(snap["totals"]) == {
            "unhealthy", "degraded", "healthy", "unknown",
        }

    def test_healthy_adapter_scored_high(self, monkeypatch):
        monkeypatch.setattr(
            dash, "_collect_sla_snapshot",
            lambda: {"rows": [{
                "adapter": "openai", "evaluated": True, "grade": "ok",
                "p95_ms": 1000, "success_rate": 1.0,
            }]},
        )
        monkeypatch.setattr(
            dash, "_collect_retries_snapshot",
            lambda: {
                "breakers": [{
                    "adapter": "openai", "state": "closed",
                    "consecutive_failures": 0, "fail_threshold": 5,
                    "trips": 0,
                }],
                "per_adapter": [{
                    "adapter": "openai", "calls": 100,
                    "retries": 0, "giveups": 0,
                }],
            },
        )
        monkeypatch.setattr(
            dash, "_collect_ratelimit_snapshot",
            lambda: {"rows": [{"adapter": "openai", "status": "ok"}]},
        )
        snap = _collect_health_snapshot()
        assert len(snap["rows"]) == 1
        row = snap["rows"][0]
        assert row["adapter"] == "openai"
        assert row["grade"] == "healthy"
        assert row["score"] >= 0.8

    def test_unhealthy_adapter_leads_output(self, monkeypatch):
        monkeypatch.setattr(
            dash, "_collect_sla_snapshot",
            lambda: {"rows": [
                {"adapter": "good", "evaluated": True, "grade": "ok",
                 "p95_ms": 500, "success_rate": 1.0},
                {"adapter": "bad", "evaluated": True, "grade": "breach",
                 "violations": ["p95 5000 > 2000"]},
            ]},
        )
        monkeypatch.setattr(
            dash, "_collect_retries_snapshot",
            lambda: {
                "breakers": [
                    {"adapter": "good", "state": "closed",
                     "consecutive_failures": 0, "fail_threshold": 5},
                    {"adapter": "bad", "state": "open", "trips": 2},
                ],
                "per_adapter": [],
            },
        )
        monkeypatch.setattr(
            dash, "_collect_ratelimit_snapshot",
            lambda: {"rows": []},
        )
        snap = _collect_health_snapshot()
        assert snap["rows"][0]["adapter"] == "bad"
        assert snap["rows"][0]["grade"] == "unhealthy"
        # Totals should count one in each of healthy / unhealthy.
        assert snap["totals"]["unhealthy"] == 1
        assert snap["totals"]["healthy"] == 1

    def test_rows_include_component_breakdown(self, monkeypatch):
        monkeypatch.setattr(
            dash, "_collect_sla_snapshot",
            lambda: {"rows": [{
                "adapter": "x", "evaluated": True, "grade": "ok",
                "p95_ms": 1000, "success_rate": 1.0,
            }]},
        )
        monkeypatch.setattr(
            dash, "_collect_retries_snapshot",
            lambda: {
                "breakers": [{
                    "adapter": "x", "state": "closed",
                    "consecutive_failures": 0, "fail_threshold": 5,
                }],
                "per_adapter": [],
            },
        )
        monkeypatch.setattr(
            dash, "_collect_ratelimit_snapshot",
            lambda: {"rows": []},
        )
        snap = _collect_health_snapshot()
        comps = snap["rows"][0]["components"]
        names = {c["name"] for c in comps}
        assert names == {"sla", "breaker", "rate_limit", "retry"}


class TestHealthEndpoint:
    def test_api_health_wraps_snapshot(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)
        monkeypatch.setattr(
            dash, "_collect_health_snapshot",
            lambda: {
                "timestamp": 1.0,
                "totals": {
                    "unhealthy": 1, "degraded": 0,
                    "healthy": 2, "unknown": 0,
                },
                "rows": [{"adapter": "x", "grade": "unhealthy", "score": 0.1}],
            },
        )
        h._api_health()
        assert captured["status"] == 200
        assert captured["payload"]["totals"]["unhealthy"] == 1

    def test_api_health_handles_collector_failure(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)

        def _boom():
            raise RuntimeError("telemetry gone")

        monkeypatch.setattr(dash, "_collect_health_snapshot", _boom)
        h._api_health()
        assert captured["status"] == 200
        assert captured["payload"]["totals"] == {
            "unhealthy": 0, "degraded": 0, "healthy": 0, "unknown": 0,
        }
        assert captured["payload"]["rows"] == []
        assert "error" in captured["payload"]
