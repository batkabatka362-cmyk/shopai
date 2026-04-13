"""Customer Effort Score Engine — effort calculator.

Calculates the overall Customer Effort Score (CES) from interaction data.
CES is measured on a 1-7 scale where 1 = very low effort, 7 = very high effort.

Lower scores are better — they indicate customers can accomplish tasks easily.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# CES rating thresholds
# ---------------------------------------------------------------------------

_LOW_EFFORT_STEPS = 3       # <= 3 steps = low effort
_MEDIUM_EFFORT_STEPS = 6    # <= 6 steps = medium effort
# > 6 steps = high effort

_LOW_EFFORT_TIME = 120      # <= 2 min = low effort (seconds)
_MEDIUM_EFFORT_TIME = 300   # <= 5 min = medium effort
# > 5 min = high effort


def calculate_effort(
    interactions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate overall Customer Effort Score from interaction data.

    Each interaction is scored individually, then aggregated into an
    overall CES. Unresolved interactions receive a penalty multiplier.

    Args:
        interactions: List of interaction dicts with customer_id,
            touchpoint, steps_taken, time_spent, resolved fields.

    Returns:
        Structured dict with ces_score and per-interaction scores.
    """
    try:
        items = copy.deepcopy(interactions)

        if not items:
            return {
                "status": "success",
                "ces_score": 0.0,
                "interaction_scores": [],
                "total_interactions": 0,
            }

        interaction_scores: list[dict[str, Any]] = []
        total_score = 0.0

        for interaction in items:
            customer_id = str(interaction.get("customer_id", "unknown"))
            touchpoint = str(interaction.get("touchpoint", "unknown"))
            steps = int(interaction.get("steps_taken", 1))
            time_spent = float(interaction.get("time_spent", 0.0))
            resolved = bool(interaction.get("resolved", True))

            # Step effort component (1-7 scale)
            if steps <= _LOW_EFFORT_STEPS:
                step_score = 1.0 + (steps / _LOW_EFFORT_STEPS) * 1.0  # 1.0-2.0
            elif steps <= _MEDIUM_EFFORT_STEPS:
                ratio = (steps - _LOW_EFFORT_STEPS) / (_MEDIUM_EFFORT_STEPS - _LOW_EFFORT_STEPS)
                step_score = 2.0 + ratio * 2.0  # 2.0-4.0
            else:
                extra = min(steps - _MEDIUM_EFFORT_STEPS, 10)
                step_score = 4.0 + (extra / 10.0) * 3.0  # 4.0-7.0

            # Time effort component (1-7 scale)
            if time_spent <= _LOW_EFFORT_TIME:
                time_score = 1.0 + (time_spent / _LOW_EFFORT_TIME) * 1.0
            elif time_spent <= _MEDIUM_EFFORT_TIME:
                ratio = (time_spent - _LOW_EFFORT_TIME) / (_MEDIUM_EFFORT_TIME - _LOW_EFFORT_TIME)
                time_score = 2.0 + ratio * 2.0
            else:
                extra = min(time_spent - _MEDIUM_EFFORT_TIME, 600)
                time_score = 4.0 + (extra / 600.0) * 3.0

            # Combined score (weighted average: steps 60%, time 40%)
            combined = round(step_score * 0.6 + time_score * 0.4, 2)

            # Unresolved penalty: increase score by 1.5x (more effort perceived)
            if not resolved:
                combined = round(min(combined * 1.5, 7.0), 2)

            total_score += combined

            interaction_scores.append({
                "customer_id": customer_id,
                "touchpoint": touchpoint,
                "effort_score": combined,
                "step_score": round(step_score, 2),
                "time_score": round(time_score, 2),
                "resolved": resolved,
            })

        avg_ces = round(total_score / len(interaction_scores), 2)

        return {
            "status": "success",
            "ces_score": avg_ces,
            "interaction_scores": interaction_scores,
            "total_interactions": len(interaction_scores),
        }
    except Exception as exc:
        return {
            "status": "error",
            "ces_score": 0.0,
            "interaction_scores": [],
            "error": f"Effort calculation failed: {exc}",
        }
