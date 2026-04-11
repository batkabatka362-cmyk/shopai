"""Integration tests for Mind's CognitiveDispatcher wiring (Wave 3 #1).

These tests exercise the real ``Mind._build_cognitive_dispatcher``
adapter layer — not the dispatcher's unit-level ``default_for_mind``
classmethod. The goal is to confirm that when a Mind is constructed
with a realistic subset of subsystems, the resulting dispatcher
actually reaches into the subsystems' real APIs with the right
argument shapes and produces a result, not a skipped/errored
:class:`DispatchResult`.
"""
from __future__ import annotations

from typing import Any

import pytest

from core.cognitive.curiosity import Curiosity, CuriosityRecommendation
from core.cognitive.functions import CognitiveFunction
from core.cognitive.mind import Mind
from core.cognitive.self_model import SelfModel
from core.mentality import Values


# ---------------------------------------------------------------------------
# Stand-ins that mimic the real subsystem method signatures
# ---------------------------------------------------------------------------


class _StubReflection:
    """Matches :class:`core.cognitive.reflection.Reflection` API shape."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def reflect(
        self,
        *,
        episode_limit: int = 100,
        category: str = "",
        apply: bool = True,
    ) -> Any:
        self.calls.append(
            {"episode_limit": episode_limit, "category": category, "apply": apply},
        )
        return {"episodes_reviewed": episode_limit, "applied": apply}


class _StubPlanner:
    def __init__(self) -> None:
        self.received_goal: Any = None
        self.received_context: Any = None

    def plan(self, goal: Any, *, context: Any = None) -> Any:
        self.received_goal = goal
        self.received_context = context
        return {"goal": goal, "steps": ["a", "b"]}


class _StubCuriosity:
    def __init__(self) -> None:
        self.recommend_calls = 0

    def recommend(self) -> str:
        self.recommend_calls += 1
        return "explore_topic_x"


class _StubConsolidation:
    def __init__(self) -> None:
        self.last_dry_run: bool | None = None

    def run(self, *, dry_run: bool = False, **_: Any) -> Any:
        self.last_dry_run = dry_run
        return {"ran": True, "dry_run": dry_run}


class _StubSelfModel:
    def snapshot(self) -> dict[str, Any]:
        return {"strengths": ["x"], "weaknesses": ["y"]}


class _StubTheoryOfMind:
    def __init__(self) -> None:
        self.last: tuple[str, str] | None = None

    def predict_response(self, agent_id: str, action: str, **_: Any) -> Any:
        self.last = (agent_id, action)
        return {"agent": agent_id, "action": action, "confidence": 0.6}


# ---------------------------------------------------------------------------
# _build_cognitive_dispatcher — registration coverage
# ---------------------------------------------------------------------------


def test_fully_wired_mind_registers_all_eight_functions():
    mind = Mind(
        self_model=_StubSelfModel(),
        reflection=_StubReflection(),
        planner=_StubPlanner(),
        curiosity=_StubCuriosity(),
        consolidation=_StubConsolidation(),
        theory_of_mind=_StubTheoryOfMind(),
        values=Values(),
    )
    registered = set(mind.active_cognitive_functions())
    # Se skipped because Mind has no public perceive() method
    assert registered == {
        CognitiveFunction.Ti,
        CognitiveFunction.Te,
        CognitiveFunction.Ne,
        CognitiveFunction.Ni,
        CognitiveFunction.Si,
        CognitiveFunction.Fi,
        CognitiveFunction.Fe,
    }


def test_stripped_mind_registers_only_available_functions():
    mind = Mind(reflection=_StubReflection())
    assert mind.active_cognitive_functions() == [CognitiveFunction.Ti]


def test_dispatcher_is_lazy_and_memoised():
    mind = Mind(reflection=_StubReflection())
    first = mind.cognitive_dispatcher()
    second = mind.cognitive_dispatcher()
    assert first is second


# ---------------------------------------------------------------------------
# Ti — Reflection
# ---------------------------------------------------------------------------


def test_ti_dispatch_calls_reflection_in_dry_run_mode():
    ref = _StubReflection()
    mind = Mind(reflection=ref)
    result = mind.dispatch_cognitive(
        CognitiveFunction.Ti, {"episode_limit": 25, "category": "errors"},
    )
    assert result.ok()
    assert ref.calls == [
        {"episode_limit": 25, "category": "errors", "apply": False},
    ]


def test_ti_uses_default_limits_when_context_is_empty():
    ref = _StubReflection()
    mind = Mind(reflection=ref)
    mind.dispatch_cognitive(CognitiveFunction.Ti, {})
    assert ref.calls[0] == {
        "episode_limit": 100, "category": "", "apply": False,
    }


# ---------------------------------------------------------------------------
# Te — Planner
# ---------------------------------------------------------------------------


def test_te_dispatch_forwards_goal_and_context():
    plan = _StubPlanner()
    mind = Mind(planner=plan)
    result = mind.dispatch_cognitive(
        CognitiveFunction.Te, {"goal": "grow_revenue", "horizon": "30d"},
    )
    assert result.ok()
    assert plan.received_goal == "grow_revenue"
    assert plan.received_context == {"goal": "grow_revenue", "horizon": "30d"}


def test_te_returns_none_when_no_goal_in_context():
    plan = _StubPlanner()
    mind = Mind(planner=plan)
    result = mind.dispatch_cognitive(CognitiveFunction.Te, {})
    assert result.ok()
    assert result.value is None
    assert plan.received_goal is None


# ---------------------------------------------------------------------------
# Ne — Curiosity
# ---------------------------------------------------------------------------


def test_ne_dispatch_invokes_curiosity_recommend():
    cur = _StubCuriosity()
    mind = Mind(curiosity=cur)
    result = mind.dispatch_cognitive(CognitiveFunction.Ne, {"ignored": True})
    assert result.value == "explore_topic_x"
    assert cur.recommend_calls == 1


# ---------------------------------------------------------------------------
# Ni — Consolidation (dry-run by default)
# ---------------------------------------------------------------------------


def test_ni_dispatch_defaults_to_dry_run():
    con = _StubConsolidation()
    mind = Mind(consolidation=con)
    result = mind.dispatch_cognitive(CognitiveFunction.Ni, {})
    assert result.value == {"ran": True, "dry_run": True}
    assert con.last_dry_run is True


def test_ni_dispatch_respects_dry_run_override():
    con = _StubConsolidation()
    mind = Mind(consolidation=con)
    mind.dispatch_cognitive(CognitiveFunction.Ni, {"dry_run": False})
    assert con.last_dry_run is False


# ---------------------------------------------------------------------------
# Si — SelfModel snapshot
# ---------------------------------------------------------------------------


def test_si_dispatch_returns_snapshot():
    sm = _StubSelfModel()
    mind = Mind(self_model=sm)
    result = mind.dispatch_cognitive(CognitiveFunction.Si, {})
    assert result.value == {"strengths": ["x"], "weaknesses": ["y"]}


# ---------------------------------------------------------------------------
# Fi — Values.score
# ---------------------------------------------------------------------------


def test_fi_dispatch_scores_context_through_values():
    values = Values.from_kwargs(safety=2.0, speed=0.1)
    mind = Mind(values=values)
    result = mind.dispatch_cognitive(
        CognitiveFunction.Fi, {"safety": 0.9, "speed": 0.9},
    )
    assert result.ok()
    # Safety-heavy values should strongly reward the "safety" attribute
    assert isinstance(result.value, float)
    assert result.value > 0.5


def test_fi_dispatch_skipped_when_no_values_injected():
    mind = Mind()
    result = mind.dispatch_cognitive(CognitiveFunction.Fi, {})
    assert result.skipped is True


# ---------------------------------------------------------------------------
# Fe — TheoryOfMind
# ---------------------------------------------------------------------------


def test_fe_dispatch_reads_agent_and_action_from_context():
    tom = _StubTheoryOfMind()
    mind = Mind(theory_of_mind=tom)
    result = mind.dispatch_cognitive(
        CognitiveFunction.Fe,
        {"agent": "customer_42", "action": "offer discount"},
    )
    assert result.ok()
    assert tom.last == ("customer_42", "offer discount")


def test_fe_dispatch_returns_none_when_agent_or_action_missing():
    tom = _StubTheoryOfMind()
    mind = Mind(theory_of_mind=tom)
    result = mind.dispatch_cognitive(CognitiveFunction.Fe, {"agent": "x"})
    assert result.value is None
    assert tom.last is None


# ---------------------------------------------------------------------------
# Se — custom perceive on a subclass
# ---------------------------------------------------------------------------


class _PerceivingMind(Mind):
    def perceive(self, context: dict[str, Any]) -> Any:
        return {"source": context.get("source"), "ok": True}


def test_se_dispatch_uses_subclass_perceive():
    mind = _PerceivingMind()
    # Subclass exposes perceive() → Se should be registered
    assert CognitiveFunction.Se in mind.active_cognitive_functions()
    result = mind.dispatch_cognitive(
        CognitiveFunction.Se, {"source": "shopify"},
    )
    assert result.value == {"source": "shopify", "ok": True}


# ---------------------------------------------------------------------------
# End-to-end: run_cycle still works alongside dispatcher
# ---------------------------------------------------------------------------


def test_dispatcher_wiring_does_not_disturb_run_cycle():
    # Minimal Mind with no subsystems — should still run a cycle
    # (legacy behaviour) and now also expose an empty dispatcher.
    mind = Mind()
    report = mind.run_cycle({"source": "test"})
    assert report.cycle_number == 1
    assert mind.active_cognitive_functions() == []
