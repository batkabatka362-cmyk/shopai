"""Wave 4 #1: CoreOrchestrator._phase_judgment uses deliberate().

The Wave 3 #2 commit added ``JudgmentAdvisor.deliberate`` — a
debate-aware wrapper around ``evaluate`` — but the orchestrator's
``_phase_judgment`` still called ``evaluate`` directly, so the
debate arbiter never fired in production.

Wave 4 #1 upgrades the call path. These tests drive the
orchestrator's phase helper directly (bypassing the full tick
loop) with a stubbed advisor to prove:

* ``deliberate`` is preferred over ``evaluate`` when available
* recalled past episodes are forwarded as ``memories``
* a legacy advisor (no ``deliberate``) still works via ``evaluate``
"""
from __future__ import annotations

from typing import Any

import pytest

from core.core_orchestrator import CoreOrchestrator


class _StubSnapshot:
    """Minimal stand-in for CoreOrchestrator.snapshot.

    The _phase_judgment helper only touches ``get_situation``.
    """

    def get_situation(self) -> dict[str, Any]:
        return {"financial": {"health": "B"}, "events": []}


class _FakeDeliberateAdvisor:
    """Records every call so we can assert the call path."""

    def __init__(self) -> None:
        self.deliberate_calls: list[dict[str, Any]] = []
        self.evaluate_calls: list[dict[str, Any]] = []

    def deliberate(self, decision, situation, *, memories=None):
        self.deliberate_calls.append(
            {"decision": decision, "situation": situation,
             "memories": list(memories or [])},
        )
        return {"verdict": "proceed", "risk_score": 0.78,
                "debate": {"triggered": True}}

    def evaluate(self, decision, situation):
        self.evaluate_calls.append(
            {"decision": decision, "situation": situation},
        )
        return {"verdict": "proceed", "risk_score": 0.78}


class _LegacyAdvisor:
    """Pre-Wave-3 advisor without a deliberate() method."""

    def __init__(self) -> None:
        self.evaluate_calls = 0

    def evaluate(self, decision, situation):
        self.evaluate_calls += 1
        return {"verdict": "proceed", "risk_score": 0.4}


@pytest.fixture
def orchestrator() -> CoreOrchestrator:
    # The full __init__ wires up a lot of modules we don't need.
    # Allocate a bare instance and attach just the two attributes
    # _phase_judgment touches.
    orch = CoreOrchestrator.__new__(CoreOrchestrator)
    orch._modules = {}
    orch.snapshot = _StubSnapshot()
    return orch


# ---------------------------------------------------------------------------
# Deliberate is preferred when available
# ---------------------------------------------------------------------------


def test_phase_judgment_uses_deliberate_when_available(orchestrator):
    advisor = _FakeDeliberateAdvisor()
    orchestrator._modules["judgment_advisor"] = advisor

    out = orchestrator._phase_judgment(
        intel={"decision": {"action": "launch"}},
        data={},
        memories=[{"success": True}, {"success": False}],
    )
    assert out["verdict"] == "proceed"
    assert out["debate"] == {"triggered": True}
    assert len(advisor.deliberate_calls) == 1
    assert advisor.evaluate_calls == []

    call = advisor.deliberate_calls[0]
    assert call["decision"] == {"action": "launch"}
    assert call["situation"]["financial"]["health"] == "B"
    # Recalled episodes forwarded as memories
    assert len(call["memories"]) == 2


def test_phase_judgment_passes_empty_memories_list_when_none(orchestrator):
    advisor = _FakeDeliberateAdvisor()
    orchestrator._modules["judgment_advisor"] = advisor

    orchestrator._phase_judgment(
        intel={"decision": {"action": "x"}}, data={},
    )
    assert advisor.deliberate_calls[0]["memories"] == []


# ---------------------------------------------------------------------------
# Legacy fallback
# ---------------------------------------------------------------------------


def test_phase_judgment_falls_back_to_evaluate_for_legacy_advisor(
    orchestrator,
):
    legacy = _LegacyAdvisor()
    orchestrator._modules["judgment_advisor"] = legacy
    out = orchestrator._phase_judgment(
        intel={"decision": {"action": "x"}}, data={},
    )
    assert legacy.evaluate_calls == 1
    assert out["verdict"] == "proceed"


# ---------------------------------------------------------------------------
# No advisor wired
# ---------------------------------------------------------------------------


def test_phase_judgment_returns_default_when_no_advisor(orchestrator):
    # _modules has no judgment_advisor
    out = orchestrator._phase_judgment(intel={}, data={})
    assert out["verdict"] == "proceed"
    assert "No judgment advisor" in out["reason"]


# ---------------------------------------------------------------------------
# Advisor raises → safe fallback
# ---------------------------------------------------------------------------


class _BoomAdvisor:
    def deliberate(self, *a, **kw):
        raise RuntimeError("advisor down")

    def evaluate(self, *a, **kw):
        raise RuntimeError("advisor down")


def test_phase_judgment_swallows_advisor_crash(orchestrator):
    orchestrator._modules["judgment_advisor"] = _BoomAdvisor()
    out = orchestrator._phase_judgment(intel={}, data={})
    assert out["verdict"] == "proceed"
    assert "Judgment error" in out["reason"]
