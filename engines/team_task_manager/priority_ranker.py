"""Team Task Manager Engine — priority ranker.

Ranks tasks by urgency and impact. Computes a composite priority score
and assigns priority levels (P0-P3).

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Urgency weights
# ---------------------------------------------------------------------------

_URGENCY_WEIGHTS: dict[str, float] = {
    "critical": 4.0,
    "high": 3.0,
    "medium": 2.0,
    "low": 1.0,
}

# Category impact multipliers (some categories inherently higher impact)
_CATEGORY_IMPACT: dict[str, float] = {
    "inventory": 1.3,
    "operations": 1.2,
    "customer_support": 1.1,
    "marketing": 1.0,
    "general": 0.9,
}


def rank_priorities(
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Rank tasks by composite priority score.

    Priority score = urgency_weight * category_impact * time_decay.
    Time decay: shorter estimated tasks get a slight bump (faster wins).

    Args:
        tasks: Assigned tasks from workload_balancer.

    Returns:
        Structured dict with priority-ranked tasks.
    """
    try:
        items = copy.deepcopy(tasks)

        ranked: list[dict[str, Any]] = []

        for task in items:
            urgency = str(task.get("urgency", "medium"))
            category = str(task.get("category", "general"))
            est_minutes = int(task.get("estimated_minutes", 30))

            urgency_w = _URGENCY_WEIGHTS.get(urgency, 2.0)
            impact_w = _CATEGORY_IMPACT.get(category, 1.0)

            # Time factor: tasks under 30 min get 1.2x, over 120 min get 0.8x
            if est_minutes <= 30:
                time_factor = 1.2
            elif est_minutes <= 120:
                time_factor = 1.0
            else:
                time_factor = 0.8

            priority_score = round(urgency_w * impact_w * time_factor, 2)

            # Assign priority level
            if priority_score >= 4.0:
                priority = "P0"
            elif priority_score >= 3.0:
                priority = "P1"
            elif priority_score >= 2.0:
                priority = "P2"
            else:
                priority = "P3"

            task["priority_score"] = priority_score
            task["priority"] = priority
            ranked.append(task)

        # Sort by priority score descending
        ranked.sort(key=lambda t: t["priority_score"], reverse=True)

        return {
            "status": "success",
            "ranked_tasks": ranked,
        }
    except Exception as exc:
        return {
            "status": "error",
            "ranked_tasks": [],
            "error": f"Priority ranking failed: {exc}",
        }
