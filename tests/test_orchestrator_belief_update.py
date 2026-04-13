"""Wave 6 #2: CoreOrchestrator feeds execution outcomes into beliefs.

Wave 2 #2 added :meth:`JudgmentAdvisor.update_belief` — a
Bayesian beta-binomial hook — but no production path ever
called it. The belief store stayed flat: decisions queried
flat posteriors because no cycle fed outcomes back in.

Wave 6 #2 wires ``_update_beliefs_from_execution`` into
``run_cycle`` so every executed action's success/failure lands
on ``advisor.update_belief`` with a stable key
(``"<target>::<action_type>"``). Running multiple cycles now
accumulates real posterior data.

These tests drive the helper directly on a bare
:class:`CoreOrchestrator` instance (via ``__new__``) — the full
``run_cycle`` path is deliberately out of scope; we only
verify the integration seam.
"""
from __future__ import annotations

from typing import Any

import pytest

from core.core_orchestrator import CoreOrchestrator


class _FakeAdvisor:
    """Capture every update_belief call with a small in-memory table."""

    def __init__(self, *, return_none: bool = False) -> None:
        self.calls: list[tuple[str, bool]] = []
        self._counts: dict[str, tuple[int, int]] = {}  # (succ, fail)
        self._return_none = return_none

    def update_belief(self, key: str, success: bool, weight: float = 1.0):
        self.calls.append((key, success))
        s, f = self._counts.get(key, (0, 0))
        if success:
            self._counts[key] = (s + 1, f)
        else:
            self._counts[key] = (s, f + 1)
        if self._return_none:
            return None
        s, f = self._counts[key]
        return {"key": key, "alpha": s + 1, "beta": f + 1,
                "mean": (s + 1) / (s + f + 2), "n": s + f}


class _LegacyAdvisor:
    """Advisor that doesn't implement update_belief."""


class _CrashAdvisor:
    def update_belief(self, key, success, weight=1.0):
        raise RuntimeError("belief store offline")


@pytest.fixture
def orchestrator() -> CoreOrchestrator:
    orch = CoreOrchestrator.__new__(CoreOrchestrator)
    orch._modules = {}
    return orch


def _execution(*results: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal execution-phase dict with the given detail rows."""
    return {
        "status":   "executed",
        "planned":  len(results),
        "executed": len(results),
        "details":  list(results),
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_updates_one_belief_per_executed_action(orchestrator):
    advisor = _FakeAdvisor()
    orchestrator._modules["judgment_advisor"] = advisor
    n = orchestrator._update_beliefs_from_execution(_execution(
        {"action_type": "pricing.update", "target": "shopify", "success": True},
        {"action_type": "pricing.update", "target": "shopify", "success": False},
        {"action_type": "product.create_listing", "target": "shopify", "success": True},
    ))
    assert n == 3
    assert advisor.calls == [
        ("shopify::pricing.update", True),
        ("shopify::pricing.update", False),
        ("shopify::product.create_listing", True),
    ]
    # After 2 pricing.update calls (1 success, 1 failure) the
    # posterior is balanced — mean = (1+1)/(1+1+2) = 0.5
    snap = advisor._counts["shopify::pricing.update"]
    assert snap == (1, 1)


def test_key_format_uses_target_and_action_type(orchestrator):
    advisor = _FakeAdvisor()
    orchestrator._modules["judgment_advisor"] = advisor
    orchestrator._update_beliefs_from_execution(_execution(
        {"action_type": "inventory.reorder", "target": "warehouse", "success": True},
    ))
    assert advisor.calls[0][0] == "warehouse::inventory.reorder"


def test_missing_action_type_falls_back_to_unknown(orchestrator):
    advisor = _FakeAdvisor()
    orchestrator._modules["judgment_advisor"] = advisor
    orchestrator._update_beliefs_from_execution(_execution(
        {"target": "shopify", "success": True},  # no action_type
    ))
    assert advisor.calls == [("shopify::unknown", True)]


def test_missing_target_falls_back_to_unknown(orchestrator):
    advisor = _FakeAdvisor()
    orchestrator._modules["judgment_advisor"] = advisor
    orchestrator._update_beliefs_from_execution(_execution(
        {"action_type": "noop.probe", "success": False},  # no target
    ))
    assert advisor.calls == [("unknown::noop.probe", False)]


# ---------------------------------------------------------------------------
# Accumulation across cycles — simulating multi-tick runs
# ---------------------------------------------------------------------------


def test_accumulates_across_multiple_calls(orchestrator):
    advisor = _FakeAdvisor()
    orchestrator._modules["judgment_advisor"] = advisor
    # Cycle 1: 2 successes
    orchestrator._update_beliefs_from_execution(_execution(
        {"action_type": "a", "target": "t", "success": True},
        {"action_type": "a", "target": "t", "success": True},
    ))
    # Cycle 2: 1 failure
    orchestrator._update_beliefs_from_execution(_execution(
        {"action_type": "a", "target": "t", "success": False},
    ))
    assert advisor._counts["t::a"] == (2, 1)


# ---------------------------------------------------------------------------
# Empty / degraded cases — always no-op, never raise
# ---------------------------------------------------------------------------


def test_empty_details_returns_zero(orchestrator):
    advisor = _FakeAdvisor()
    orchestrator._modules["judgment_advisor"] = advisor
    assert orchestrator._update_beliefs_from_execution(_execution()) == 0
    assert advisor.calls == []


def test_missing_details_key_returns_zero(orchestrator):
    advisor = _FakeAdvisor()
    orchestrator._modules["judgment_advisor"] = advisor
    n = orchestrator._update_beliefs_from_execution({"status": "executed"})
    assert n == 0


def test_non_dict_execution_returns_zero(orchestrator):
    advisor = _FakeAdvisor()
    orchestrator._modules["judgment_advisor"] = advisor
    assert orchestrator._update_beliefs_from_execution("not a dict") == 0  # type: ignore[arg-type]
    assert orchestrator._update_beliefs_from_execution(None) == 0  # type: ignore[arg-type]


def test_no_advisor_returns_zero_and_does_not_raise(orchestrator):
    # _modules has no judgment_advisor
    n = orchestrator._update_beliefs_from_execution(_execution(
        {"action_type": "a", "target": "t", "success": True},
    ))
    assert n == 0


def test_legacy_advisor_without_update_belief_returns_zero(orchestrator):
    orchestrator._modules["judgment_advisor"] = _LegacyAdvisor()
    n = orchestrator._update_beliefs_from_execution(_execution(
        {"action_type": "a", "target": "t", "success": True},
    ))
    assert n == 0


def test_advisor_crash_is_swallowed(orchestrator):
    orchestrator._modules["judgment_advisor"] = _CrashAdvisor()
    # One crashing result followed by another — both should be
    # attempted, both should return 0 updated, no exception
    n = orchestrator._update_beliefs_from_execution(_execution(
        {"action_type": "a", "target": "t", "success": True},
        {"action_type": "b", "target": "t", "success": False},
    ))
    assert n == 0


def test_advisor_returning_none_does_not_count_update(orchestrator):
    """When update_belief returns None (no belief store attached),
    the helper skips the counter — matches the plan's 'degraded
    deployments silently no-op' rule."""
    advisor = _FakeAdvisor(return_none=True)
    orchestrator._modules["judgment_advisor"] = advisor
    n = orchestrator._update_beliefs_from_execution(_execution(
        {"action_type": "a", "target": "t", "success": True},
        {"action_type": "b", "target": "t", "success": True},
    ))
    # Calls were made but none counted as updates
    assert len(advisor.calls) == 2
    assert n == 0


# ---------------------------------------------------------------------------
# Input validation — malformed rows are skipped, not raised
# ---------------------------------------------------------------------------


def test_non_dict_detail_row_is_skipped(orchestrator):
    advisor = _FakeAdvisor()
    orchestrator._modules["judgment_advisor"] = advisor
    n = orchestrator._update_beliefs_from_execution(_execution(
        {"action_type": "a", "target": "t", "success": True},
    ))
    # Manually mix in a bad row
    bad_exec = {"status": "executed", "details": [
        "not-a-dict",  # skipped
        {"action_type": "b", "target": "t", "success": False},
        None,  # skipped
    ]}
    n2 = orchestrator._update_beliefs_from_execution(bad_exec)
    assert n == 1
    assert n2 == 1
    assert advisor.calls == [
        ("t::a", True),
        ("t::b", False),
    ]
