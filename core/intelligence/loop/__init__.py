"""IntelligenceLoop — the BRAIN of ShopAI.

ONE connected loop: Data -> Decision -> Execution -> Result -> Learning -> Better Decision

Stages:
  1. CLEAN   — validate, fix, score data quality
  2. ANALYZE — compute scores, detect patterns, assess opportunity
  3. DECIDE  — rank multiple options, apply learning, calculate real confidence
  4. PLAN    — create specific executable actions
  5. EXECUTE — format for target systems (Shopify, email, ads)
  6. TRACK   — record what was decided and why
  7. LEARN   — compare outcomes, adjust weights, feed back to stage 3
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

from .weight_manager import get_learned_weights
from .stage_clean import stage_clean
from .stage_analyze import stage_analyze
from .stage_decide import stage_decide
from .stage_plan import stage_plan
from .stage_execute import stage_execute
from .stage_track import stage_track
from .stage_learn import stage_learn
from .helpers import summarize, abort

logger = get_logger("intelligence_loop")

# Learning hyperparameters — exposed as module-level constants
LEARNABLE_FACTORS = ("margin", "demand", "competition", "shipping", "rating", "review", "price", "velocity")
MAX_ADJUSTMENT = 0.30  # Maximum deviation from base weight
RATE = 0.05            # How fast to adjust (small = stable, large = reactive)
DECAY = 0.95           # How fast old learning fades (0.95 = 5% decay per cycle)

__all__ = ["IntelligenceLoop", "get_learned_weights"]


class IntelligenceLoop:
    """Complete closed intelligence loop with multi-factor confidence and adaptive learning."""

    # Expose constants as class attributes
    LEARNABLE_FACTORS = LEARNABLE_FACTORS
    MAX_ADJUSTMENT = MAX_ADJUSTMENT
    LEARNING_RATE = RATE
    DECAY = DECAY

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []

    def run(self, raw_data: dict[str, Any], goal: str = "maximize_profit") -> dict[str, Any]:
        loop_id = generate_id("loop")
        start = time.monotonic()
        context: dict[str, Any] = {"loop_id": loop_id, "goal": goal, "raw_data": raw_data}

        # Stage 1: CLEAN
        clean_result = stage_clean(raw_data)
        context["clean"] = clean_result

        if clean_result["quality_score"] < 20:
            return abort(loop_id, "Data quality too low", clean_result, start)

        # Stage 2: ANALYZE
        analysis = stage_analyze(clean_result["data"], goal)
        context["analysis"] = analysis

        # Stage 3: DECIDE — multi-option with real confidence
        decision = stage_decide(analysis, clean_result, goal)
        context["decision"] = decision

        # Stage 4: PLAN
        plan = stage_plan(decision, clean_result["data"])
        context["plan"] = plan

        # Stage 5: EXECUTE
        execution = stage_execute(plan, clean_result["data"])
        context["execution"] = execution

        # Stage 6: TRACK
        stage_track(loop_id, context)

        # Stage 7: LEARN
        learning = stage_learn(loop_id, decision)
        context["learning"] = learning

        elapsed = time.monotonic() - start

        result = {
            "loop_id": loop_id,
            "goal": goal,
            "elapsed_seconds": round(elapsed, 3),
            "data_quality": clean_result["quality_score"],
            "decision": {
                "action": decision["recommended_action"],
                "confidence": decision["confidence"],
                "confidence_score": decision["confidence_score"],
                "reason": decision["reason"],
                "options_evaluated": decision.get("options_evaluated", 0),
                "opportunity_score": decision.get("opportunity_score", 0),
            },
            "plan": {
                "actions": len(plan["actions"]),
                "priority_1": [a for a in plan["actions"] if a["priority"] == 1],
            },
            "execution": {
                "ready_actions": len(execution["ready"]),
                "targets": list(set(a["target"] for a in execution["ready"])),
            },
            "learning": {
                "past_outcomes": learning["past_outcomes"],
                "adjusted": learning["adjustments_made"],
                "advice": learning["advice"],
                "weight_adjustments": learning.get("weight_adjustments", {}),
            },
            "stages_completed": 7,
            "summary": summarize(decision, plan, execution, learning, elapsed),
        }

        self._history.append(result)
        return result

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self._history[-limit:])
