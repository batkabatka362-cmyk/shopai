"""Integration tests for JudgmentAdvisor.deliberate (Wave 3 #2).

`deliberate` wraps the advisor's existing `evaluate` with the Wave 2
#8 debate layer, but only when the risk score lands inside the
uncertainty band ``[PROCEED_THRESHOLD, DELAY_THRESHOLD]``. These
tests drive the advisor with synthetic decisions that land in each
of the three regions (proceed / band / escalate) and assert the
debate attachment behaves correctly.
"""
from __future__ import annotations

from typing import Any

import pytest

from core.brain.debate import DELAY_THRESHOLD, PROCEED_THRESHOLD
from core.judgment.judgment_advisor import JudgmentAdvisor
from core.mentality import Values


# ---------------------------------------------------------------------------
# Helpers: fabricate advisor payloads with a controllable risk score
# ---------------------------------------------------------------------------


def _advisor_with_forced_risk(risk: float) -> JudgmentAdvisor:
    """Return a JudgmentAdvisor whose evaluate() always reports *risk*.

    This is a focused integration probe — we want to drive deliberate()
    through each of its three code paths without having to hand-craft
    decisions/situations that naturally land on a boundary.
    """
    advisor = JudgmentAdvisor(values=Values())

    def _stub_evaluate(decision, situation):
        return {
            "verdict": "proceed",
            "risk_score": risk,
            "checks": [
                {"name": "magnitude", "risk": risk, "weight": 0.2, "score": risk},
                {"name": "past_failures", "risk": risk, "weight": 0.25, "score": risk * 0.7},
            ],
            "reason": "forced",
            "recommendations": [],
            "degraded_checks": 0,
        }

    advisor.evaluate = _stub_evaluate  # type: ignore[method-assign]
    return advisor


def _decision() -> dict[str, Any]:
    return {"action": "launch campaign", "confidence_score": 60}


def _situation() -> dict[str, Any]:
    return {"financial": {"health": "A"}, "events": []}


# ---------------------------------------------------------------------------
# Band behaviour
# ---------------------------------------------------------------------------


def test_deliberate_skips_debate_below_band():
    advisor = _advisor_with_forced_risk(0.40)
    out = advisor.deliberate(_decision(), _situation())
    assert out["risk_score"] == 0.40
    assert out["debate"] is None


def test_deliberate_skips_debate_above_band():
    advisor = _advisor_with_forced_risk(0.95)
    out = advisor.deliberate(_decision(), _situation())
    assert out["debate"] is None


def test_deliberate_runs_debate_inside_band():
    advisor = _advisor_with_forced_risk(0.78)
    out = advisor.deliberate(_decision(), _situation())
    debate = out["debate"]
    assert debate is not None
    assert debate["triggered"] is True
    assert debate["proposals"] == 5
    assert "winner_persona" in debate
    # Inside the band, all five default personas should have weighed in
    personas = {row["persona"] for row in debate["scored"]}
    assert personas == {
        "Analyzer", "Planner", "Executor", "Critic", "MemoryManager",
    }


def test_deliberate_fires_at_lower_boundary():
    advisor = _advisor_with_forced_risk(PROCEED_THRESHOLD)
    out = advisor.deliberate(_decision(), _situation())
    assert out["debate"] is not None


def test_deliberate_fires_at_upper_boundary():
    advisor = _advisor_with_forced_risk(DELAY_THRESHOLD)
    out = advisor.deliberate(_decision(), _situation())
    assert out["debate"] is not None


# ---------------------------------------------------------------------------
# Values propagation: safety-heavy operator should favour Critic/Analyzer
# ---------------------------------------------------------------------------


def test_safety_values_bias_debate_winner_toward_cautious_personas():
    safety = Values.from_kwargs(
        safety=5.0, reliability=5.0, long_term=5.0,
        speed=0.1, short_term=0.1,
    )
    advisor = JudgmentAdvisor(values=safety)

    def _stub_evaluate(d, s):
        return {
            "verdict": "delay",
            "risk_score": 0.80,
            "checks": [
                {"name": "magnitude", "risk": 0.9, "weight": 0.2, "score": 0.9},
                {"name": "past_failures", "risk": 0.5, "weight": 0.25, "score": 0.5},
            ],
            "reason": "",
            "recommendations": [],
            "degraded_checks": 0,
        }

    advisor.evaluate = _stub_evaluate  # type: ignore[method-assign]
    out = advisor.deliberate(_decision(), _situation())
    winner = out["debate"]["winner_persona"]
    # Critic / Analyzer / Planner are the safety-heavy voices
    assert winner in {"Critic", "Analyzer", "Planner"}


def test_speed_values_bias_debate_winner_toward_executor():
    speed = Values.from_kwargs(
        safety=0.1, reliability=0.1, long_term=0.1,
        speed=5.0, short_term=5.0, automation=2.0,
    )
    advisor = JudgmentAdvisor(values=speed)

    def _stub_evaluate(d, s):
        return {
            "verdict": "delay",
            "risk_score": 0.78,
            "checks": [
                {"name": "magnitude", "risk": 0.5, "weight": 0.2, "score": 0.5},
            ],
            "reason": "",
            "recommendations": [],
            "degraded_checks": 0,
        }

    advisor.evaluate = _stub_evaluate  # type: ignore[method-assign]
    out = advisor.deliberate(_decision(), _situation())
    assert out["debate"]["winner_persona"] == "Executor"


# ---------------------------------------------------------------------------
# Memories forwarded to MemoryManager persona
# ---------------------------------------------------------------------------


def test_deliberate_forwards_memories_to_debate_memory_manager():
    advisor = _advisor_with_forced_risk(0.78)
    successes = [{"success": True} for _ in range(4)]
    failures = [{"success": False} for _ in range(1)]
    out = advisor.deliberate(
        _decision(), _situation(), memories=successes + failures,
    )
    # Pull the MemoryManager row out of the scored breakdown. The
    # debate as_dict serialises rows as dicts with "persona" / "score"
    # / "confidence" fields.
    scored = out["debate"]["scored"]
    mm_rows = [row for row in scored if row["persona"] == "MemoryManager"]
    assert len(mm_rows) == 1
    # With a 4/5 success rate the MemoryManager's confidence
    # should be reasonably high (above neutral)
    assert mm_rows[0]["confidence"] > 0.5


def test_deliberate_without_memories_still_runs_debate():
    advisor = _advisor_with_forced_risk(0.78)
    out = advisor.deliberate(_decision(), _situation())
    debate = out["debate"]
    assert debate is not None
    assert debate["proposals"] == 5


# ---------------------------------------------------------------------------
# Advisor without operator values falls back to neutral Values
# ---------------------------------------------------------------------------


def test_deliberate_uses_neutral_values_when_advisor_has_none():
    advisor = JudgmentAdvisor()  # no values injected

    def _stub_evaluate(d, s):
        return {
            "verdict": "delay",
            "risk_score": 0.78,
            "checks": [],
            "reason": "",
            "recommendations": [],
            "degraded_checks": 0,
        }

    advisor.evaluate = _stub_evaluate  # type: ignore[method-assign]
    out = advisor.deliberate(_decision(), _situation())
    # Debate still runs; neutral values don't crash the arbiter
    assert out["debate"] is not None
    assert out["debate"]["triggered"] is True


# ---------------------------------------------------------------------------
# deliberate preserves the rest of the advisor payload
# ---------------------------------------------------------------------------


def test_deliberate_preserves_advisor_fields():
    advisor = _advisor_with_forced_risk(0.78)
    out = advisor.deliberate(_decision(), _situation())
    assert out["verdict"] == "proceed"  # from stub
    assert out["risk_score"] == 0.78
    assert "checks" in out
    assert "reason" in out
    assert "debate" in out
