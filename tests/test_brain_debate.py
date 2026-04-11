"""Tests for core.brain.debate (Wave 2 #8)."""
from __future__ import annotations

import pytest

from core.brain.debate import (
    DebateArbiter,
    DebateContext,
    DebateOutcome,
    Proposal,
    analyzer,
    critic,
    executor,
    memory_manager,
    planner,
    should_debate,
)
from core.judgment.judgment_advisor import (
    DELAY_THRESHOLD,
    PROCEED_THRESHOLD,
)
from core.mentality import Values


# ---------------------------------------------------------------------------
# should_debate thresholds
# ---------------------------------------------------------------------------


def test_should_debate_inside_band():
    assert should_debate(0.75) is True
    assert should_debate(0.80) is True


def test_should_debate_at_boundaries_is_true():
    assert should_debate(PROCEED_THRESHOLD) is True
    assert should_debate(DELAY_THRESHOLD) is True


def test_should_debate_below_band():
    assert should_debate(0.5) is False
    assert should_debate(0.0) is False


def test_should_debate_above_band():
    assert should_debate(0.9) is False
    assert should_debate(1.0) is False


def test_should_debate_custom_band():
    assert should_debate(0.4, lower=0.3, upper=0.5) is True
    assert should_debate(0.6, lower=0.3, upper=0.5) is False


# ---------------------------------------------------------------------------
# Individual persona shape
# ---------------------------------------------------------------------------


def _ctx(**kwargs) -> DebateContext:
    return DebateContext(
        decision=kwargs.get("decision", {"action": "launch campaign"}),
        situation=kwargs.get("situation", {}),
        advisor_result=kwargs.get("advisor_result", {}),
        memories=kwargs.get("memories", []),
    )


def test_analyzer_returns_proposal():
    p = analyzer(_ctx(situation={"financial": {"health": "A"}, "events": []}))
    assert isinstance(p, Proposal)
    assert p.persona == "Analyzer"
    assert "safety" in p.principles
    assert 0 <= p.confidence <= 1


def test_planner_emits_phased_mode():
    p = planner(_ctx())
    assert p.persona == "Planner"
    assert p.action_patch["mode"] == "phased"
    assert p.action_patch["rollback_ready"] is True


def test_executor_biases_speed():
    p = executor(_ctx())
    assert p.persona == "Executor"
    assert p.principles["speed"] > p.principles["safety"]
    assert p.action_patch["mode"] == "ship"


def test_critic_uses_advisor_concern():
    p = critic(_ctx(advisor_result={
        "risk_score": 0.82,
        "checks": [
            {"name": "magnitude", "score": 0.9},
            {"name": "past_failures", "score": 0.3},
        ],
    }))
    assert p.persona == "Critic"
    assert p.action_patch["concern"] == "magnitude"
    assert p.action_patch["escalate"] is True
    assert p.principles["safety"] >= 0.9


def test_critic_with_no_checks_uses_fallback_concern():
    p = critic(_ctx(advisor_result={"risk_score": 0.75}))
    assert p.action_patch["concern"] == "general risk"


def test_memory_manager_pattern_matches_on_memories():
    successes = [{"success": True} for _ in range(8)]
    failures = [{"success": False} for _ in range(2)]
    p = memory_manager(_ctx(memories=successes + failures))
    # 8/10 = 80% success rate
    assert p.persona == "MemoryManager"
    assert p.action_patch["precedent_success_rate"] == pytest.approx(0.8)
    assert p.principles["safety"] > 0.6


def test_memory_manager_empty_memories_defaults_neutral():
    p = memory_manager(_ctx(memories=[]))
    assert p.action_patch["precedent_success_rate"] == 0.5


# ---------------------------------------------------------------------------
# DebateArbiter
# ---------------------------------------------------------------------------


def test_arbiter_runs_all_default_personas():
    arb = DebateArbiter(values=Values())
    outcome = arb.run(_ctx())
    assert outcome.triggered is True
    assert outcome.proposals == 5
    assert {p.persona for p, _ in outcome.scored} == {
        "Analyzer", "Planner", "Executor", "Critic", "MemoryManager",
    }


def test_arbiter_picks_highest_scored_proposal():
    # Safety-heavy values should favour Critic over Executor
    safety = Values.from_kwargs(
        safety=5.0, reliability=5.0, long_term=5.0,
        speed=0.1, short_term=0.1,
    )
    arb = DebateArbiter(values=safety)
    outcome = arb.run(_ctx(advisor_result={"risk_score": 0.8}))
    top_persona = outcome.scored[0][0].persona
    assert top_persona in {"Critic", "Analyzer", "Planner"}
    # Winner should be the first-scored proposal
    assert outcome.winner is outcome.scored[0][0]


def test_arbiter_speed_values_favours_executor():
    speed = Values.from_kwargs(
        safety=0.1, reliability=0.1, long_term=0.1,
        speed=5.0, short_term=5.0, automation=2.0,
    )
    arb = DebateArbiter(values=speed)
    outcome = arb.run(_ctx())
    assert outcome.winner.persona == "Executor"


def test_arbiter_tiebreak_prefers_critic():
    # Custom personas: critic and executor produce identical scores
    def tied_critic(ctx):
        return Proposal(
            persona="Critic", summary="tied", principles={"safety": 1.0},
        )
    def tied_executor(ctx):
        return Proposal(
            persona="Executor", summary="tied", principles={"safety": 1.0},
        )

    arb = DebateArbiter(
        values=Values.from_kwargs(safety=1.0),
        personas=[tied_executor, tied_critic],
    )
    outcome = arb.run(_ctx())
    # Two proposals with identical score 1.0 — Critic wins tiebreak
    assert outcome.winner.persona == "Critic"


def test_arbiter_skips_failing_persona():
    def bad(ctx):
        raise RuntimeError("boom")

    arb = DebateArbiter(
        values=Values(),
        personas=[analyzer, bad, planner],
    )
    outcome = arb.run(_ctx())
    assert outcome.proposals == 2
    assert {p.persona for p, _ in outcome.scored} == {"Analyzer", "Planner"}


def test_arbiter_raises_when_no_proposals_valid():
    def nothing(ctx):
        return None

    arb = DebateArbiter(values=Values(), personas=[nothing])
    with pytest.raises(RuntimeError, match="no valid proposals"):
        arb.run(_ctx())


def test_arbiter_add_persona_extends_lineup():
    arb = DebateArbiter(values=Values(), personas=[analyzer])
    assert len(arb.personas()) == 1
    arb.add_persona(planner)
    assert len(arb.personas()) == 2


def test_arbiter_carries_advisor_risk_score_into_outcome():
    arb = DebateArbiter(values=Values())
    outcome = arb.run(_ctx(advisor_result={"risk_score": 0.77}))
    assert outcome.risk_score == 0.77


def test_outcome_as_dict_has_expected_shape():
    arb = DebateArbiter(values=Values())
    outcome = arb.run(_ctx())
    d = outcome.as_dict()
    assert set(d.keys()) >= {
        "winner_persona", "winner_summary", "scored",
        "triggered", "risk_score", "proposals",
    }
    assert len(d["scored"]) == 5


# ---------------------------------------------------------------------------
# End-to-end: advisor + should_debate + arbiter
# ---------------------------------------------------------------------------


def test_e2e_advisor_band_triggers_debate():
    # Synthetic advisor output sitting inside the band
    advisor_result = {
        "risk_score": 0.78,
        "checks": [
            {"name": "magnitude",    "score": 0.8},
            {"name": "past_failures", "score": 0.6},
        ],
    }
    assert should_debate(advisor_result["risk_score"])
    arb = DebateArbiter(values=Values())
    outcome = arb.run(_ctx(advisor_result=advisor_result))
    assert outcome.triggered is True
    assert outcome.winner is not None
