"""Time Intelligence — priority analyzer.

Analyzes and assigns priority scores based on urgency, deadline proximity,
dependency count, and business impact.

Model note: Would use Mistral for priority/dependency reasoning.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

_URGENCY_WEIGHTS: dict[str, float] = {
    "immediate": 1.0,
    "urgent": 0.8,
    "normal": 0.5,
    "deferred": 0.2,
}

_DOMAIN_IMPACT: dict[str, float] = {
    "orders": 0.95,
    "pricing": 0.90,
    "inventory": 0.80,
    "marketing": 0.75,
    "communication": 0.60,
    "analytics": 0.50,
    "catalog": 0.55,
    "infrastructure": 0.40,
    "general": 0.50,
}

_CLASSIFICATION_BOOST: dict[str, float] = {
    "realtime": 0.15,
    "triggered": 0.10,
    "scheduled": 0.0,
    "batch": -0.05,
}


def analyze_priorities(
    classified_tasks: list[dict[str, Any]],
    completed_tasks: list[str],
    current_time: str,
) -> dict[str, Any]:
    """Assign priority scores to all classified tasks.

    Args:
        classified_tasks: Tasks from the classifier stage.
        completed_tasks: List of already-completed task type strings.
        current_time: ISO timestamp of current time.

    Returns:
        Structured dict with priority results per task.
    """
    try:
        classified_tasks = copy.deepcopy(classified_tasks)
        results = []

        for task in classified_tasks:
            task_id = task["task_id"]
            urgency = task.get("urgency", "normal")
            deadline = task.get("deadline")
            dependencies = task.get("dependencies", [])
            domain = task.get("domain", "general")
            classification = task.get("classification", "batch")

            urgency_w = _URGENCY_WEIGHTS.get(urgency, 0.5)
            deadline_w = _compute_deadline_weight(deadline, current_time)
            dep_w = _compute_dependency_weight(dependencies, completed_tasks)
            impact = _DOMAIN_IMPACT.get(domain, 0.5)
            class_boost = _CLASSIFICATION_BOOST.get(classification, 0.0)

            raw_score = (
                urgency_w * 0.30
                + deadline_w * 0.25
                + dep_w * 0.15
                + impact * 0.30
                + class_boost
            )

            priority_score = max(0.0, min(1.0, raw_score))

            results.append({
                "task_id": task_id,
                "priority_score": round(priority_score, 4),
                "urgency_weight": round(urgency_w, 4),
                "deadline_weight": round(deadline_w, 4),
                "dependency_weight": round(dep_w, 4),
                "business_impact": round(impact, 4),
                "model_note": "Mistral: priority reasoning",
            })

        results.sort(key=lambda r: r["priority_score"], reverse=True)

        return {
            "status": "success",
            "priority_results": results,
            "count": len(results),
        }
    except Exception as exc:
        return {
            "status": "error",
            "priority_results": [],
            "count": 0,
            "error": str(exc),
        }


def _compute_deadline_weight(deadline: str | None, current_time: str) -> float:
    """Compute weight based on how close the deadline is."""
    if not deadline:
        return 0.3

    try:
        deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        current_dt = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
        hours_remaining = (deadline_dt - current_dt).total_seconds() / 3600.0

        if hours_remaining <= 0:
            return 1.0
        if hours_remaining <= 1:
            return 0.95
        if hours_remaining <= 6:
            return 0.85
        if hours_remaining <= 12:
            return 0.75
        if hours_remaining <= 24:
            return 0.60
        if hours_remaining <= 48:
            return 0.45
        if hours_remaining <= 72:
            return 0.35
        return 0.2
    except (ValueError, TypeError):
        return 0.3


def _compute_dependency_weight(
    dependencies: list[str],
    completed_tasks: list[str],
) -> float:
    """Compute weight based on dependency resolution status."""
    if not dependencies:
        return 1.0

    resolved = sum(1 for dep in dependencies if dep in completed_tasks)
    total = len(dependencies)

    if resolved == total:
        return 1.0
    ratio = resolved / total
    return round(0.2 + (ratio * 0.6), 4)
