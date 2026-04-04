"""Customer Effort Score Engine — touchpoint scorer.

Aggregates effort scores per touchpoint to identify which channels/touchpoints
require the most customer effort. Groups interactions by touchpoint and
computes average effort, resolution rate, and volume.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any


def score_touchpoints(
    interaction_efforts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score each touchpoint by aggregating effort data.

    Args:
        interaction_efforts: Per-interaction effort data from effort_calculator.

    Returns:
        Structured dict with per-touchpoint scores.
    """
    try:
        items = copy.deepcopy(interaction_efforts)
        if not items:
            return {
                "status": "success",
                "touchpoint_scores": [],
            }

        # Group by touchpoint
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            tp = str(item.get("touchpoint", "unknown"))
            groups[tp].append(item)

        touchpoint_scores: list[dict[str, Any]] = []

        for touchpoint, entries in groups.items():
            efforts = [float(e.get("effort_score", 0.0)) for e in entries]
            resolved_count = sum(1 for e in entries if e.get("resolved", False))
            total = len(entries)
            avg_steps = round(
                sum(int(e.get("steps_taken", 0)) for e in entries) / total, 1
            )
            avg_time = round(
                sum(float(e.get("time_spent", 0.0)) for e in entries) / total, 1
            )

            avg_effort = round(sum(efforts) / len(efforts), 2)
            resolution_rate = round(resolved_count / total, 4) if total > 0 else 0.0

            # Grade: A (<=2), B (<=3), C (<=4), D (<=5), F (>5)
            if avg_effort <= 2.0:
                grade = "A"
            elif avg_effort <= 3.0:
                grade = "B"
            elif avg_effort <= 4.0:
                grade = "C"
            elif avg_effort <= 5.0:
                grade = "D"
            else:
                grade = "F"

            touchpoint_scores.append({
                "touchpoint": touchpoint,
                "avg_effort_score": avg_effort,
                "grade": grade,
                "volume": total,
                "resolution_rate": resolution_rate,
                "avg_steps": avg_steps,
                "avg_time_seconds": avg_time,
            })

        # Sort worst touchpoints first (highest effort)
        touchpoint_scores.sort(key=lambda t: t["avg_effort_score"], reverse=True)

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
