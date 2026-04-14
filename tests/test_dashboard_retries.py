"""Dashboard retry/breaker endpoint — Option R phase 3.

Tests the ``_collect_retries_snapshot`` rollup and the
``/api/retries`` handler wiring.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.adapters.retry import (
    RetryOutcome,
    RetryTelemetry,
)
from dashboard import app as dash
from dashboard.app import DashboardAPIHandler, _collect_retries_snapshot


class _Result:
    def __init__(self, ok: bool, error=None):
        self.ok = ok
        self.error = error


def _handler() -> DashboardAPIHandler:
    return object.__new__(DashboardAPIHandler)


class TestCollectRetriesSnapshot:
    def test_empty_state_is_zeroed(self, monkeypatch):
        # Fresh telemetry + no router instance.
        monkeypatch.setattr(
            "core.adapters.retry._default_telemetry", RetryTelemetry(),
        )
        from core.adapters import router as router_mod
        monkeypatch.setattr(router_mod, "_router", None, raising=False)

        snap = _collect_retries_snapshot()
        assert snap["totals"] == {"calls": 0, "retries": 0, "giveups": 0}
        assert snap["per_adapter"] == []
        assert snap["breakers"] == []

    def test_per_adapter_rollup_sorted_by_pain(self, monkeypatch):
        t = RetryTelemetry()
        # quiet adapter: 1 call, 0 retries
        t.record("quiet", RetryOutcome(
            result=_Result(ok=True), attempts=[],
            retried=False, gave_up=False,
        ))
        # noisy adapter: 2 calls, both retried, one gave up
        t.record("noisy", RetryOutcome(
            result=_Result(ok=True), attempts=[],
            retried=True, gave_up=False,
        ))
        t.record("noisy", RetryOutcome(
            result=_Result(ok=False), attempts=[],
            retried=True, gave_up=True,
        ))
        monkeypatch.setattr(
            "core.adapters.retry._default_telemetry", t,
        )
        from core.adapters import router as router_mod
        monkeypatch.setattr(router_mod, "_router", None, raising=False)

        snap = _collect_retries_snapshot()
        names = [r["adapter"] for r in snap["per_adapter"]]
        # "noisy" leads because retries+giveups is higher.
        assert names[0] == "noisy"
        assert snap["totals"]["retries"] == 2
        assert snap["totals"]["giveups"] == 1

    def test_breakers_included_when_router_exists(self, monkeypatch):
        monkeypatch.setattr(
            "core.adapters.retry._default_telemetry", RetryTelemetry(),
        )
        fake_router = MagicMock()
        fake_router.breaker_snapshot.return_value = {
            "openai": {
                "state": "open",
                "consecutive_failures": 5,
                "trips": 2,
                "fail_threshold": 5,
                "reset_after_s": 30.0,
            },
        }
        from core.adapters import router as router_mod
        monkeypatch.setattr(router_mod, "_router", fake_router, raising=False)

        snap = _collect_retries_snapshot()
        assert len(snap["breakers"]) == 1
        assert snap["breakers"][0]["adapter"] == "openai"
        assert snap["breakers"][0]["state"] == "open"
        assert snap["breakers"][0]["trips"] == 2

    def test_breaker_snapshot_failure_fails_soft(self, monkeypatch):
        monkeypatch.setattr(
            "core.adapters.retry._default_telemetry", RetryTelemetry(),
        )
        fake_router = MagicMock()
        fake_router.breaker_snapshot.side_effect = RuntimeError("boom")
        from core.adapters import router as router_mod
        monkeypatch.setattr(router_mod, "_router", fake_router, raising=False)

        snap = _collect_retries_snapshot()
        assert snap["breakers"] == []


class TestRetriesEndpoint:
    def test_api_retries_wraps_snapshot(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)
        monkeypatch.setattr(
            dash, "_collect_retries_snapshot",
            lambda: {
                "timestamp": 1.0,
                "totals": {"calls": 1, "retries": 0, "giveups": 0},
                "per_adapter": [{"adapter": "x", "calls": 1}],
                "breakers": [],
            },
        )
        h._api_retries()
        assert captured["status"] == 200
        assert captured["payload"]["totals"]["calls"] == 1

    def test_api_retries_handles_collector_failure(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)

        def _boom():
            raise RuntimeError("collector down")

        monkeypatch.setattr(dash, "_collect_retries_snapshot", _boom)
        h._api_retries()
        assert captured["status"] == 200
        assert captured["payload"]["totals"]["calls"] == 0
        assert "error" in captured["payload"]
