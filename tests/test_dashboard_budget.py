"""Dashboard budget endpoint — Option T phase 3.

Tests the ``_collect_budget_snapshot`` rollup and the ``/api/budget``
handler wiring.
"""
from __future__ import annotations

import pytest

from core.adapters.budget import (
    BudgetEnforcer,
    CostBudget,
    reset_budget_enforcer,
)
from dashboard import app as dash
from dashboard.app import DashboardAPIHandler, _collect_budget_snapshot


def _handler() -> DashboardAPIHandler:
    return object.__new__(DashboardAPIHandler)


@pytest.fixture(autouse=True)
def _reset_enforcer():
    reset_budget_enforcer()
    yield
    reset_budget_enforcer()


class TestCollectBudgetSnapshot:
    def test_empty_returns_zero_totals(self):
        snap = _collect_budget_snapshot()
        assert snap["rows"] == []
        assert snap["totals"] == {
            "exceeded": 0, "warn": 0, "ok": 0, "unconfigured": 0,
        }

    def test_totals_rolled_up_from_rows(self, monkeypatch):
        enf = BudgetEnforcer(budgets={
            "hot": CostBudget(daily_usd=1.0),
            "warm": CostBudget(daily_usd=1.0),
            "fine": CostBudget(daily_usd=1.0),
        })
        enf.record("hot", 2.0)     # exceeded
        enf.record("warm", 0.85)   # warn
        enf.record("fine", 0.1)    # ok
        monkeypatch.setattr(
            "core.adapters.budget.get_budget_enforcer", lambda: enf,
        )
        snap = _collect_budget_snapshot()
        assert snap["totals"]["exceeded"] == 1
        assert snap["totals"]["warn"] == 1
        assert snap["totals"]["ok"] == 1

    def test_unconfigured_spender_counted(self, monkeypatch):
        enf = BudgetEnforcer()
        enf.record("wild", 5.0)
        monkeypatch.setattr(
            "core.adapters.budget.get_budget_enforcer", lambda: enf,
        )
        snap = _collect_budget_snapshot()
        assert snap["totals"]["unconfigured"] == 1
        assert snap["rows"][0]["adapter"] == "wild"


class TestBudgetEndpoint:
    def test_api_budget_wraps_snapshot(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)
        monkeypatch.setattr(
            dash, "_collect_budget_snapshot",
            lambda: {
                "timestamp": 1.0,
                "totals": {"exceeded": 1, "warn": 0, "ok": 2, "unconfigured": 0},
                "rows": [{"adapter": "x", "status": "ok"}],
            },
        )
        h._api_budget()
        assert captured["status"] == 200
        assert captured["payload"]["totals"]["exceeded"] == 1

    def test_api_budget_handles_collector_failure(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)

        def _boom():
            raise RuntimeError("enforcer gone")

        monkeypatch.setattr(dash, "_collect_budget_snapshot", _boom)
        h._api_budget()
        assert captured["status"] == 200
        assert captured["payload"]["totals"] == {
            "exceeded": 0, "warn": 0, "ok": 0, "unconfigured": 0,
        }
        assert "error" in captured["payload"]
