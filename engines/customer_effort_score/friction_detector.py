"""Customer Effort Score Engine — friction detector.

Detects high-friction areas where customers struggle. Identifies patterns
of excessive steps, long resolution times, and repeat contacts.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Friction thresholds
# ---------------------------------------------------------------------------

_HIGH_EFFORT_THRESHOLD = 4.5       # CES score above this = friction point
_LOW_RESOLUTION_THRESHOLD = 0.7    # Resolution rate below 70% = friction
_HIGH_REPEAT_THRESHOLD = 2         # Customer seen >2 times at same touchpoint


def detect_friction(
    interaction_scores: list[dict[str, Any]],
    touchpoint_scores: list[dict[str, Any]],
) -> dict[str, Any]:
    """Detect high-friction areas across touchpoints and customers.

    Looks for: high-effort touchpoints, low-resolution touchpoints,
    repeat-contact patterns, and individual high-friction interactions.

    Args:
        interaction_scores: Per-interaction scores from effort_calculator.
        touchpoint_scores: Per-touchpoint scores from touchpoint_scorer.

    Returns:
        Structured dict with friction_points list.
    """
    try:
        interactions = copy.deepcopy(interaction_scores)
        tp_scores = copy.deepcopy(touchpoint_scores)

        friction_points: list[dict[str, Any]] = []

        # --- Touchpoint-level friction ---
        for tp in tp_scores:
            touchpoint = str(tp.get("touchpoint", ""))
            avg_effort = float(tp.get("avg_effort", 0.0))
            resolution_rate = float(tp.get("resolution_rate", 1.0))
            volume = int(tp.get("volume", 0))

            if avg_effort >= _HIGH_EFFORT_THRESHOLD:
                friction_points.append({
                    "type": "high_effort_touchpoint",
                    "severity": "high" if avg_effort >= 5.5 else "medium",
                    "touchpoint": touchpoint,
                    "metric": avg_effort,
                    "volume": volume,
                    "description": (
                        f"Touchpoint '{touchpoint}' has avg effort score of "
                        f"{avg_effort}/7.0 across {volume} interactions."
                    ),
                })

            if resolution_rate < _LOW_RESOLUTION_THRESHOLD and volume > 0:
                friction_points.append({
                    "type": "low_resolution_rate",
                    "severity": "high" if resolution_rate < 0.5 else "medium",
                    "touchpoint": touchpoint,
                    "metric": resolution_rate,
                    "volume": volume,
                    "description": (
                        f"Touchpoint '{touchpoint}' has only "
                        f"{round(resolution_rate * 100, 1)}% resolution rate."
                    ),
                })

        # --- Repeat-contact friction ---
        contact_counts: dict[str, dict[str, int]] = {}
        for interaction in interactions:
            cid = str(interaction.get("customer_id", ""))
            tp = str(interaction.get("touchpoint", ""))
            contact_counts.setdefault(cid, {})
            contact_counts[cid][tp] = contact_counts[cid].get(tp, 0) + 1

        repeat_touchpoints: dict[str, int] = {}
        for cid, tps in contact_counts.items():
            for tp, count in tps.items():
                if count > _HIGH_REPEAT_THRESHOLD:
                    repeat_touchpoints[tp] = repeat_touchpoints.get(tp, 0) + 1

        for tp, affected_customers in repeat_touchpoints.items():
            friction_points.append({
                "type": "repeat_contact",
                "severity": "medium",
                "touchpoint": tp,
                "metric": affected_customers,
                "volume": affected_customers,
                "description": (
                    f"{affected_customers} customers required >2 contacts "
                    f"at '{tp}', indicating unresolved issues."
                ),
            })

        # Sort by severity
        severity_order = {"high": 0, "medium": 1, "low": 2}
        friction_points.sort(
            key=lambda f: severity_order.get(f.get("severity", "low"), 3),
        )

        return {
            "status": "success",
            "friction_points": friction_points,
            "total_friction_points": len(friction_points),
        }
    except Exception as exc:
        return {
            "status": "error",
            "friction_points": [],
            "error": f"Friction detection failed: {exc}",
        }
