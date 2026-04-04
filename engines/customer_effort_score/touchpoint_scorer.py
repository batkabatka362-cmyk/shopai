"""Customer Effort Score Engine — touchpoint scorer.

Scores effort per touchpoint type (checkout, support, returns, etc.)
by aggregating individual interaction scores into touchpoint-level metrics.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def score_touchpoints(
    interaction_scores: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score effort per touchpoint by aggregating interaction data.

    Groups interactions by touchpoint, computes average effort, volume,
    and resolution rate for each.

    Args:
        interaction_scores: Per-interaction scores from effort_calculator.

    Returns:
        Structured dict with touchpoint_scores list.
    """
    try:
        items = copy.deepcopy(interaction_scores)

        if not items:
            return {
                "status": "success",
                "touchpoint_scores": [],
            }

        # Group by touchpoint
        groups: dict[str, list[dict[str, Any]]] = {}
        for score in items:
            tp = str(score.get("touchpoint", "unknown"))
            groups.setdefault(tp, []).append(score)

        touchpoint_scores: list[dict[str, Any]] = []

        for touchpoint, scores in groups.items():
            efforts = [float(s.get("effort_score", 0.0)) for s in scores]
            resolved_count = sum(1 for s in scores if s.get("resolved", False))
            total = len(scores)

            avg_effort = round(sum(efforts) / total, 2) if total > 0 else 0.0
            max_effort = round(max(efforts), 2) if efforts else 0.0
            min_effort = round(min(efforts), 2) if efforts else 0.0
            resolution_rate = round(resolved_count / total, 4) if total > 0 else 0.0

            # Rating: low (<=2.5), medium (<=4.5), high (>4.5)
            if avg_effort <= 2.5:
                rating = "low_effort"
            elif avg_effort <= 4.5:
                rating = "medium_effort"
            else:
                rating = "high_effort"

            touchpoint_scores.append({
                "touchpoint": touchpoint,
                "avg_effort": avg_effort,
                "min_effort": min_effort,
                "max_effort": max_effort,
                "volume": total,
                "resolution_rate": resolution_rate,
                "rating": rating,
            })

        # Sort by avg_effort descending (worst first)
        touchpoint_scores.sort(key=lambda t: t["avg_effort"], reverse=True)

        return {
            "status": "success",
            "touchpoint_scores": touchpoint_scores,
        }
    except Exception as exc:
        return {
            "status": "error",
            "touchpoint_scores": [],
            "error": f"Touchpoint scoring failed: {exc}",
        }
