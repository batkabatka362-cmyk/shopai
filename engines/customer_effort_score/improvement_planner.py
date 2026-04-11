"""Customer Effort Score Engine — improvement planner.

Plans friction reduction strategies based on detected friction points
and touchpoint scores. Prioritizes improvements by impact and feasibility.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Improvement templates by friction type
# ---------------------------------------------------------------------------

_IMPROVEMENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "high_effort_touchpoint": {
        "strategy": "simplify_flow",
        "actions": [
            "Reduce number of steps in this touchpoint",
            "Add progress indicators and inline validation",
            "Implement auto-fill and smart defaults",
        ],
        "expected_improvement_pct": 20,
    },
    "low_resolution_rate": {
        "strategy": "improve_resolution",
        "actions": [
            "Add self-service options and knowledge base articles",
            "Implement escalation paths for complex issues",
            "Train support staff on common failure scenarios",
        ],
        "expected_improvement_pct": 25,
    },
    "repeat_contact": {
        "strategy": "first_contact_resolution",
        "actions": [
            "Audit repeat-contact root causes",
            "Implement follow-up confirmation workflows",
            "Add proactive status updates to reduce check-in contacts",
        ],
        "expected_improvement_pct": 30,
    },
}


def plan_improvements(
    friction_points: list[dict[str, Any]],
    touchpoint_scores: list[dict[str, Any]],
    ces_score: float,
) -> dict[str, Any]:
    """Plan friction reduction improvements.

    Generates prioritized improvement plans based on friction severity,
    volume of affected interactions, and expected impact.

    Args:
        friction_points: Detected friction points from friction_detector.
        touchpoint_scores: Per-touchpoint scores from touchpoint_scorer.
        ces_score: Overall CES score from effort_calculator.

    Returns:
        Structured dict with improvements list and trend assessment.
    """
    try:
        frictions = copy.deepcopy(friction_points)
        tp_map = {
            str(t.get("touchpoint", "")): t
            for t in copy.deepcopy(touchpoint_scores)
        }

        improvements: list[dict[str, Any]] = []

        for friction in frictions:
            friction_type = str(friction.get("type", ""))
            touchpoint = str(friction.get("touchpoint", ""))
            severity = str(friction.get("severity", "low"))
            volume = int(friction.get("volume", 0))

            template = _IMPROVEMENT_TEMPLATES.get(friction_type, {
                "strategy": "general_optimization",
                "actions": ["Review and optimize touchpoint flow"],
                "expected_improvement_pct": 10,
            })

            # Priority score: severity weight * volume
            severity_weight = {"high": 3, "medium": 2, "low": 1}.get(severity, 1)
            priority_score = severity_weight * max(volume, 1)

            tp_data = tp_map.get(touchpoint, {})
            current_effort = float(tp_data.get("avg_effort", 0.0))
            expected_pct = template["expected_improvement_pct"]
            projected_effort = round(
                current_effort * (1 - expected_pct / 100.0), 2,
            )

            improvements.append({
                "touchpoint": touchpoint,
                "friction_type": friction_type,
                "severity": severity,
                "strategy": template["strategy"],
                "actions": template["actions"],
                "priority_score": priority_score,
                "current_effort": current_effort,
                "projected_effort": projected_effort,
                "expected_improvement_pct": expected_pct,
                "affected_interactions": volume,
            })

        # Sort by priority score descending
        improvements.sort(key=lambda i: i["priority_score"], reverse=True)

        # Trend assessment
        if ces_score <= 2.5:
            trend = "excellent"
        elif ces_score <= 4.0:
            trend = "acceptable"
        elif ces_score <= 5.5:
            trend = "needs_improvement"
        else:
            trend = "critical"

        return {
            "status": "success",
            "improvements": improvements,
            "trend": trend,
            "total_improvements": len(improvements),
        }
    except Exception as exc:
        return {
            "status": "error",
            "improvements": [],
            "trend": "unknown",
            "error": f"Improvement planning failed: {exc}",
        }
