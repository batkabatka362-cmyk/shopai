"""Router + budget enforcer integration — Option T phase 2.

Validates that ``SmartRouter`` honours the attached budget enforcer:

* per-adapter budget blocks dispatch when the daily cap would be
  exceeded, forcing the router onto its fallback
* per-call caps reject calls whose estimated cost is too high
* realised cost is booked into the ledger after a successful call
* the enforcer is exposed via ``router.budget_enforcer`` so dashboards
  can snapshot it
"""
from __future__ import annotations

from core.adapters import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
    SmartRouter,
    get_registry,
    reset_registry,
)
from core.adapters.budget import (
    BudgetEnforcer,
    CostBudget,
)


class _CostyAdapter(BaseAdapter):
    """Adapter with a settable per-call cost."""

    def __init__(self, *, name: str, priority: int = 50, cost: float = 0.0):
        self.name = name
        self.capabilities = {Capability.CHAT_COMPLETE}
        self.category = AdapterCategory.LLM
        self.priority = priority
        self.cost_per_call = cost
        super().__init__()
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    def _execute(self, capability, params):
        self.calls += 1
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"text": "ok"},
            cost_usd=self.cost_per_call,
        )


def _router_with(enforcer: BudgetEnforcer, *adapters) -> SmartRouter:
    reset_registry()
    reg = get_registry()
    for a in adapters:
        reg.register(a)
    return SmartRouter(registry=reg, budget_enforcer=enforcer)


class TestBudgetGateSkipsOverrun:
    def test_blocked_primary_falls_through(self):
        expensive = _CostyAdapter(name="expensive", priority=99, cost=0.50)
        cheap = _CostyAdapter(name="cheap", priority=50, cost=0.001)
        enf = BudgetEnforcer(budgets={
            "expensive": CostBudget(daily_usd=0.10),
        })
        # Pre-spend to nearly the cap so the next call would cross it.
        enf.record("expensive", 0.09)
        router = _router_with(enf, expensive, cheap)
        result = router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        assert result.ok
        assert result.adapter == "cheap"
        assert expensive.calls == 0

    def test_per_call_cap_rejects(self):
        big = _CostyAdapter(name="big", priority=99, cost=1.0)
        small = _CostyAdapter(name="small", priority=50, cost=0.01)
        enf = BudgetEnforcer(budgets={
            "big": CostBudget(per_call_usd=0.10),
        })
        router = _router_with(enf, big, small)
        result = router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        assert result.ok
        assert result.adapter == "small"
        assert big.calls == 0

    def test_no_budget_lets_everything_through(self):
        expensive = _CostyAdapter(name="expensive", priority=99, cost=0.50)
        enf = BudgetEnforcer()   # empty catalog
        router = _router_with(enf, expensive)
        result = router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        assert result.ok
        assert result.adapter == "expensive"
        assert expensive.calls == 1


class TestLedgerRecording:
    def test_successful_call_books_cost(self):
        a = _CostyAdapter(name="a", cost=0.25)
        enf = BudgetEnforcer(budgets={
            "a": CostBudget(daily_usd=10.0),
        })
        router = _router_with(enf, a)
        router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        daily, monthly = enf.ledger.spent("a")
        assert daily == 0.25
        assert monthly == 0.25

    def test_zero_cost_does_not_book(self):
        a = _CostyAdapter(name="a", cost=0.0)
        enf = BudgetEnforcer(budgets={
            "a": CostBudget(daily_usd=10.0),
        })
        router = _router_with(enf, a)
        router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        assert enf.ledger.spent("a") == (0.0, 0.0)


class TestAccessor:
    def test_budget_enforcer_property(self):
        enf = BudgetEnforcer()
        router = SmartRouter(registry=get_registry(), budget_enforcer=enf)
        assert router.budget_enforcer is enf
