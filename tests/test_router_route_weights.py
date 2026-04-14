"""Integration tests for router ↔ route_weights — Upgrade 1.

The router's ``_candidates`` method multiplies each scored
adapter by its learned weight (``route_weights.get``). These
tests drive the real router with two adapters of equal priority,
penalize one, and assert the penalized one is ranked last.

We use a hand-built registry so the tests don't depend on the
full adapter catalogue.
"""
from __future__ import annotations

import pytest

from core.adapters.base import BaseAdapter, Capability
from core.adapters.registry import AdapterRegistry
from core.adapters.route_weights import (
    get_route_weight_ledger,
    reset_route_weight_ledger,
)
from core.adapters.router import RouteContext, SmartRouter


class _Stub(BaseAdapter):
    """Minimal configured adapter stub."""

    def __init__(self, name: str, priority: int = 50):
        self._name = name
        self._priority = priority
        self._caps = [Capability.CHAT_COMPLETE]

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def capabilities(self):
        return self._caps

    @property
    def cost_per_call(self) -> float:
        return 0.0

    def is_configured(self) -> bool:
        return True

    def estimate_cost(self, capability, params) -> float:
        return 0.0

    def execute(self, capability, params):  # pragma: no cover
        raise NotImplementedError

    def _execute(self, capability, params):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _isolate():
    reset_route_weight_ledger()
    yield
    reset_route_weight_ledger()


def _make_router() -> SmartRouter:
    reg = AdapterRegistry()
    reg.register(_Stub("alpha"))
    reg.register(_Stub("beta"))
    # Both have identical priority so any difference in ordering
    # must come from the weight ledger.
    return SmartRouter(registry=reg)


class TestRouterWeightOrdering:
    def test_unpenalized_ordering_alphabetical(self):
        """Ties broken by name — baseline before weights apply."""
        r = _make_router()
        cands = r.candidates(
            Capability.CHAT_COMPLETE, RouteContext(),
        )
        names = [c.name for c in cands]
        # Both priority 50 → tie → sorted by name ascending
        assert names == ["alpha", "beta"]

    def test_penalized_adapter_ranked_last(self):
        r = _make_router()
        get_route_weight_ledger().penalize(
            "alpha", Capability.CHAT_COMPLETE.value, 0.1,
        )
        cands = r.candidates(
            Capability.CHAT_COMPLETE, RouteContext(),
        )
        names = [c.name for c in cands]
        assert names[-1] == "alpha"
        assert names[0] == "beta"

    def test_symmetric_penalties_yield_both(self):
        """After equal penalties, neither candidate is systematically
        preferred. Exact order depends on sub-microsecond decay
        timing (the ledger applies decay-before-penalty), so we
        only assert both are still returned — and that a
        subsequent much-larger penalty on one flips the order."""
        r = _make_router()
        led = get_route_weight_ledger()
        led.penalize("alpha", Capability.CHAT_COMPLETE.value, 0.5)
        led.penalize("beta", Capability.CHAT_COMPLETE.value, 0.5)
        cands = r.candidates(
            Capability.CHAT_COMPLETE, RouteContext(),
        )
        names = [c.name for c in cands]
        assert set(names) == {"alpha", "beta"}

        # Now penalize beta heavily and verify alpha moves ahead.
        led.penalize("beta", Capability.CHAT_COMPLETE.value, 0.05)
        cands = r.candidates(
            Capability.CHAT_COMPLETE, RouteContext(),
        )
        names = [c.name for c in cands]
        assert names[0] == "alpha"
        assert names[1] == "beta"

    def test_weight_only_applies_to_matching_capability(self):
        r = _make_router()
        # Penalize on a DIFFERENT capability — should not affect
        # ordering of llm_complete lookups.
        get_route_weight_ledger().penalize(
            "alpha", "web_search", 0.1,
        )
        cands = r.candidates(
            Capability.CHAT_COMPLETE, RouteContext(),
        )
        names = [c.name for c in cands]
        assert names == ["alpha", "beta"]

    def test_additive_penalty_not_multiplicative(self):
        """Self-critique fix: multiplying a NEGATIVE score by a
        weight < 1 makes the score LARGER (better rank), which
        silently inverts the penalty. The fix uses additive
        subtraction proportional to priority so a penalized
        adapter always ranks below an equal-priority clean one,
        regardless of score sign."""
        reg = AdapterRegistry()
        # Both priority 50, both clean → tied; penalty on alpha
        # must push alpha below beta in every sign regime.
        reg.register(_Stub("alpha", priority=50))
        reg.register(_Stub("beta", priority=50))
        r = SmartRouter(registry=reg)
        get_route_weight_ledger().penalize(
            "alpha", Capability.CHAT_COMPLETE.value, 0.1,
        )
        cands = r.candidates(
            Capability.CHAT_COMPLETE, RouteContext(),
        )
        names = [c.name for c in cands]
        assert names[0] == "beta"
        assert names[-1] == "alpha"

    def test_penalized_candidate_still_eligible(self):
        """Floor (0.05) means even a heavily-penalized adapter is
        still returned, just last."""
        r = _make_router()
        led = get_route_weight_ledger()
        for _ in range(20):
            led.penalize(
                "alpha", Capability.CHAT_COMPLETE.value, 0.1,
            )
        cands = r.candidates(
            Capability.CHAT_COMPLETE, RouteContext(),
        )
        names = [c.name for c in cands]
        assert "alpha" in names  # never fully excluded
        assert names[-1] == "alpha"
