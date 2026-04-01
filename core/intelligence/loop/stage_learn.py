"""Stage 7: LEARN — Bayesian incremental weight updates from outcomes."""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_float
from .weight_manager import _learned_weights, _save_weights
from .helpers import avg_decision_field


# Learning hyperparameters
LEARNING_RATE = 0.05   # How fast to adjust
DECAY = 0.95           # How fast old learning fades
MAX_ADJUSTMENT = 0.30  # Maximum deviation from base weight

LEARNABLE_FACTORS = ("margin", "demand", "competition", "shipping", "rating", "review", "price", "velocity")


def stage_learn(loop_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    """Compare outcomes, adjust weights, feed back to stage 3."""
    try:
        from core.learning.outcome_tracker import OutcomeTracker
        ot = OutcomeTracker()
        patterns = ot.get_winning_patterns("intelligence_loop")

        adjustments = []
        success_rate = patterns.get("success_rate", 0.5)

        if success_rate < 0.4:
            adjustments.append("Low success rate — strategy adjustment needed")
        if success_rate > 0.7:
            adjustments.append("High success rate — continue current approach")

        # Bayesian incremental weight updates for ALL factors
        entries = ot._load("intelligence_loop")
        outcomes = [e for e in entries if e.get("outcome") is not None]
        successes = [e for e in outcomes if e.get("success")]
        failures = [e for e in outcomes if not e.get("success")]

        if successes and failures:
            for factor in LEARNABLE_FACTORS:
                score_key = f"{factor}_score" if factor != "price" else "price_point_score"
                success_avg = avg_decision_field(successes, score_key)
                failure_avg = avg_decision_field(failures, score_key)

                if success_avg is not None and failure_avg is not None:
                    if success_avg > failure_avg + 0.5:
                        _update_weight(factor, +1)
                        adjustments.append(f"{factor}: success avg {success_avg:.1f} > fail avg {failure_avg:.1f} → boost")
                    elif failure_avg > success_avg + 0.5:
                        _update_weight(factor, -1)
                        adjustments.append(f"{factor}: fail avg {failure_avg:.1f} > success avg {success_avg:.1f} → reduce")
                    else:
                        _decay_weight(factor)
        elif outcomes:
            for factor in LEARNABLE_FACTORS:
                _decay_weight(factor)

        # Pattern-based meta-learning
        for p in patterns.get("patterns", []):
            if p.get("pattern") == "high_confidence_wins":
                _learned_weights["confidence_boost"] = min(
                    _learned_weights.get("confidence_boost", 0) + 0.02, 0.2
                )
                adjustments.append("High confidence → success: boosting confidence factor")

            if p.get("pattern") == "quality_matters":
                _learned_weights["quality_gate"] = min(
                    _learned_weights.get("quality_gate", 40) + 2, 70
                )
                adjustments.append("Data quality matters: raising quality threshold")

        # Persist all weight changes
        if adjustments or outcomes:
            _save_weights()

        advice_result = ot.should_proceed("intelligence_loop", decision)

        return {
            "past_outcomes": patterns.get("with_outcomes", 0),
            "success_rate": patterns.get("success_rate", 0),
            "adjustments_made": len(adjustments) > 0,
            "adjustments": adjustments,
            "advice": advice_result.get("reasons", ["No past data — first run"]),
            "patterns": patterns.get("patterns", []),
            "weight_adjustments": dict(_learned_weights),
        }
    except Exception:
        return {
            "past_outcomes": 0, "success_rate": 0,
            "adjustments_made": False, "adjustments": [],
            "advice": ["Learning unavailable"], "patterns": [],
            "weight_adjustments": {},
        }


def _update_weight(factor: str, direction: int) -> None:
    """Bayesian incremental weight update: small steps, bounded."""
    current = _learned_weights.get(factor, 0.0)
    current *= DECAY
    current += LEARNING_RATE * direction
    _learned_weights[factor] = max(-MAX_ADJUSTMENT, min(MAX_ADJUSTMENT, round(current, 4)))


def _decay_weight(factor: str) -> None:
    """Decay weight toward zero when no clear signal."""
    current = _learned_weights.get(factor, 0.0)
    if abs(current) > 0.001:
        _learned_weights[factor] = round(current * DECAY, 4)
