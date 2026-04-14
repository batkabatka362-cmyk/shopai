"""Adapter cost budget enforcement — Option T.

Exercises the primitives in ``core.adapters.budget``:

* ``CostBudget`` — validation on construction
* ``BudgetLedger.record`` / ``.spent`` / ``.snapshot`` + wall-clock reset
* ``BudgetEnforcer.can_call`` — per-call, daily, monthly caps
* ``BudgetEnforcer.snapshot`` — dashboard rollup + grade
* Singleton helpers
"""
from __future__ import annotations

import pytest

from core.adapters.budget import (
    BudgetDecision,
    BudgetEnforcer,
    BudgetLedger,
    CostBudget,
    get_budget_enforcer,
    reset_budget_enforcer,
)


# ---------------------------------------------------------------------------
# CostBudget
# ---------------------------------------------------------------------------


class TestCostBudget:
    def test_defaults_are_none(self):
        b = CostBudget()
        assert b.daily_usd is None
        assert b.monthly_usd is None
        assert b.per_call_usd is None

    def test_rejects_negative(self):
        with pytest.raises(ValueError):
            CostBudget(daily_usd=-1)
        with pytest.raises(ValueError):
            CostBudget(monthly_usd=-0.01)
        with pytest.raises(ValueError):
            CostBudget(per_call_usd=-5)

    def test_to_dict_shape(self):
        d = CostBudget(daily_usd=1.0, monthly_usd=30.0, per_call_usd=0.1).to_dict()
        assert d == {
            "daily_usd": 1.0, "monthly_usd": 30.0, "per_call_usd": 0.1,
        }


# ---------------------------------------------------------------------------
# BudgetLedger
# ---------------------------------------------------------------------------


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class TestLedger:
    def test_unknown_adapter_zero(self):
        led = BudgetLedger()
        assert led.spent("nope") == (0.0, 0.0)

    def test_record_accumulates(self):
        led = BudgetLedger()
        led.record("x", 0.25)
        led.record("x", 0.75)
        assert led.spent("x") == (1.0, 1.0)

    def test_zero_or_negative_ignored(self):
        led = BudgetLedger()
        led.record("x", 0)
        led.record("x", -1.0)
        assert led.spent("x") == (0.0, 0.0)

    def test_daily_reset_rolls_over(self):
        clk = _Clock()
        led = BudgetLedger(clock=clk)
        led.record("x", 1.0)
        daily, monthly = led.spent("x")
        assert daily == 1.0
        assert monthly == 1.0
        # Skip past the daily reset.
        clk.advance(25 * 3600)
        led.record("x", 0.5)
        daily, monthly = led.spent("x")
        assert daily == 0.5         # reset
        assert monthly == 1.5       # cumulative

    def test_monthly_reset_rolls_over(self):
        clk = _Clock()
        led = BudgetLedger(clock=clk)
        led.record("x", 10.0)
        clk.advance(31 * 86400)
        led.record("x", 2.0)
        daily, monthly = led.spent("x")
        assert monthly == 2.0       # monthly reset
        assert daily == 2.0         # daily reset too

    def test_snapshot_returns_both_windows(self):
        led = BudgetLedger()
        led.record("a", 0.5)
        led.record("b", 1.25)
        snap = led.snapshot()
        assert snap["a"]["spent_daily_usd"] == 0.5
        assert snap["b"]["spent_daily_usd"] == 1.25
        assert snap["a"]["call_count_daily"] == 1
        assert snap["b"]["call_count_daily"] == 1

    def test_reset_one_adapter(self):
        led = BudgetLedger()
        led.record("a", 0.5)
        led.record("b", 1.0)
        led.reset("a")
        assert led.spent("a") == (0.0, 0.0)
        assert led.spent("b") == (1.0, 1.0)

    def test_reset_all(self):
        led = BudgetLedger()
        led.record("a", 0.5)
        led.record("b", 1.0)
        led.reset()
        assert led.spent("a") == (0.0, 0.0)
        assert led.spent("b") == (0.0, 0.0)


# ---------------------------------------------------------------------------
# BudgetEnforcer.can_call
# ---------------------------------------------------------------------------


class TestEnforcerGate:
    def test_no_budget_always_allows(self):
        enf = BudgetEnforcer()
        decision = enf.can_call("anything", estimated_cost_usd=10.0)
        assert decision.allow is True
        assert decision.reason == ""
        assert decision.daily_used_pct is None

    def test_per_call_cap_rejects(self):
        enf = BudgetEnforcer(budgets={
            "x": CostBudget(per_call_usd=0.10),
        })
        d = enf.can_call("x", estimated_cost_usd=0.50)
        assert d.allow is False
        assert "per-call" in d.reason

    def test_per_call_cap_allows_small(self):
        enf = BudgetEnforcer(budgets={
            "x": CostBudget(per_call_usd=0.10),
        })
        d = enf.can_call("x", estimated_cost_usd=0.05)
        assert d.allow is True

    def test_daily_cap_prevents_overrun(self):
        enf = BudgetEnforcer(budgets={
            "x": CostBudget(daily_usd=1.0),
        })
        enf.record("x", 0.80)
        # Any additional call that would cross $1.00 is rejected.
        d = enf.can_call("x", estimated_cost_usd=0.50)
        assert d.allow is False
        assert "daily" in d.reason

    def test_daily_cap_allows_under(self):
        enf = BudgetEnforcer(budgets={
            "x": CostBudget(daily_usd=1.0),
        })
        enf.record("x", 0.50)
        d = enf.can_call("x", estimated_cost_usd=0.20)
        assert d.allow is True

    def test_monthly_cap_prevents_overrun(self):
        enf = BudgetEnforcer(budgets={
            "x": CostBudget(monthly_usd=10.0),
        })
        enf.record("x", 9.5)
        d = enf.can_call("x", estimated_cost_usd=1.0)
        assert d.allow is False
        assert "monthly" in d.reason

    def test_used_pct_in_decision(self):
        enf = BudgetEnforcer(budgets={
            "x": CostBudget(daily_usd=2.0, monthly_usd=50.0),
        })
        enf.record("x", 0.5)
        d = enf.can_call("x", estimated_cost_usd=0.0)
        assert d.daily_used_pct == 0.25
        assert d.monthly_used_pct == 0.01


# ---------------------------------------------------------------------------
# Snapshot + grading
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_empty_returns_empty(self):
        assert BudgetEnforcer().snapshot() == []

    def test_grade_ok_under_80pct(self):
        enf = BudgetEnforcer(budgets={
            "x": CostBudget(daily_usd=1.0),
        })
        enf.record("x", 0.10)
        row = enf.snapshot()[0]
        assert row["status"] == "ok"

    def test_grade_warn_at_80pct(self):
        enf = BudgetEnforcer(budgets={
            "x": CostBudget(daily_usd=1.0),
        })
        enf.record("x", 0.85)
        row = enf.snapshot()[0]
        assert row["status"] == "warn"

    def test_grade_exceeded_at_100pct(self):
        enf = BudgetEnforcer(budgets={
            "x": CostBudget(daily_usd=1.0),
        })
        enf.record("x", 1.5)
        row = enf.snapshot()[0]
        assert row["status"] == "exceeded"
        # daily_used_pct clamps at 1.0 for display
        assert row["daily_used_pct"] == 1.0

    def test_unconfigured_spender_listed(self):
        # No budget, but has spend — dashboard still surfaces it.
        enf = BudgetEnforcer()
        enf.record("wild", 3.0)
        row = enf.snapshot()[0]
        assert row["adapter"] == "wild"
        assert row["status"] == "unconfigured"
        assert row["budget"] is None

    def test_budgeted_no_spend_listed(self):
        enf = BudgetEnforcer(budgets={
            "x": CostBudget(daily_usd=5.0),
        })
        rows = enf.snapshot()
        assert len(rows) == 1
        assert rows[0]["adapter"] == "x"
        assert rows[0]["spent_daily_usd"] == 0.0


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_budget_enforcer_is_stable(self):
        a = get_budget_enforcer()
        b = get_budget_enforcer()
        assert a is b

    def test_reset_replaces(self):
        a = get_budget_enforcer()
        reset_budget_enforcer()
        b = get_budget_enforcer()
        assert a is not b
