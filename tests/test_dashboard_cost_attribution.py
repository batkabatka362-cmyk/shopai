"""Dashboard cost-attribution endpoint — Option Z phase 3.

Tests ``_collect_cost_attribution_snapshot`` and the ``/api/cost-
attribution`` handler.
"""
from __future__ import annotations

import pytest

from core.adapters.cost_ledger import CostLedger, reset_cost_ledger
import core.adapters.cost_ledger as _cl_mod
from dashboard import app as dash
from dashboard.app import (
    DashboardAPIHandler,
    _collect_cost_attribution_snapshot,
)


def _handler() -> DashboardAPIHandler:
    return object.__new__(DashboardAPIHandler)


def _install_ledger(monkeypatch, ledger):
    monkeypatch.setattr(_cl_mod, "_default_ledger", ledger)


@pytest.fixture(autouse=True)
def _reset():
    reset_cost_ledger()
    yield
    reset_cost_ledger()


class TestCollectCostAttributionSnapshot:
    def test_empty_ledger_empty_rollup(self, monkeypatch):
        _install_ledger(monkeypatch, CostLedger())
        snap = _collect_cost_attribution_snapshot()
        assert snap["total_usd"] == 0.0
        assert snap["rows"] == []
        assert snap["per_caller"] == []
        assert snap["overflow"]["active"] is False

    def test_populated_ledger_rolls_up(self, monkeypatch):
        lg = CostLedger()
        lg.record(caller="a", adapter="openai", capability="chat", usd=0.10)
        lg.record(caller="a", adapter="anthropic", capability="chat", usd=0.05)
        lg.record(caller="b", adapter="openai", capability="chat", usd=0.20)
        _install_ledger(monkeypatch, lg)
        snap = _collect_cost_attribution_snapshot()
        assert snap["total_usd"] == pytest.approx(0.35)
        assert len(snap["rows"]) == 3
        assert len(snap["per_caller"]) == 2
        # Caller "b" spent more, so it should lead the per-caller list.
        assert snap["per_caller"][0]["caller"] == "b"

    def test_overflow_flagged(self, monkeypatch):
        lg = CostLedger(max_keys=2)
        for i in range(5):
            lg.record(
                caller=f"c{i}", adapter="openai", capability="chat",
                usd=0.01,
            )
        _install_ledger(monkeypatch, lg)
        snap = _collect_cost_attribution_snapshot()
        assert snap["overflow"]["active"] is True
        assert snap["overflow"]["calls"] == 3


class TestCostAttributionEndpoint:
    def test_handler_wraps_snapshot(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)
        monkeypatch.setattr(
            dash, "_collect_cost_attribution_snapshot",
            lambda: {
                "timestamp": 1.0,
                "total_usd": 0.42,
                "key_count": 3,
                "max_keys": 2048,
                "overflow": {"active": False, "calls": 0, "usd": 0.0},
                "per_caller": [{"caller": "a", "total_usd": 0.42}],
                "rows": [{"caller": "a", "adapter": "openai",
                          "capability": "chat", "total_usd": 0.42}],
            },
        )
        h._api_cost_attribution()
        assert captured["status"] == 200
        assert captured["payload"]["total_usd"] == 0.42
        assert captured["payload"]["per_caller"][0]["caller"] == "a"

    def test_handler_handles_collector_failure(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)

        def _boom():
            raise RuntimeError("ledger gone")

        monkeypatch.setattr(
            dash, "_collect_cost_attribution_snapshot", _boom,
        )
        h._api_cost_attribution()
        assert captured["status"] == 200
        assert captured["payload"]["total_usd"] == 0.0
        assert captured["payload"]["rows"] == []
        assert "error" in captured["payload"]
