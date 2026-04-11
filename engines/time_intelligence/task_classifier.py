"""Time Intelligence — task classifier.

Classifies tasks by execution type (realtime, batch, scheduled, triggered),
urgency level, and business domain.

Model note: Would use Mistral for nuanced classification reasoning.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any

_TYPE_CLASSIFICATION_MAP: dict[str, str] = {
    "launch_ad": "triggered",
    "update_inventory": "batch",
    "send_email": "scheduled",
    "process_order": "realtime",
    "generate_report": "batch",
    "sync_catalog": "batch",
    "notify_customer": "triggered",
    "run_campaign": "scheduled",
    "restock_alert": "realtime",
    "price_update": "realtime",
    "backup_data": "scheduled",
    "analyze_trends": "batch",
}

_DOMAIN_MAP: dict[str, str] = {
    "launch_ad": "marketing",
    "update_inventory": "inventory",
    "send_email": "communication",
    "process_order": "orders",
    "generate_report": "analytics",
    "sync_catalog": "catalog",
    "notify_customer": "communication",
    "run_campaign": "marketing",
    "restock_alert": "inventory",
    "price_update": "pricing",
    "backup_data": "infrastructure",
    "analyze_trends": "analytics",
}

_URGENCY_PRIORITY_MAP: dict[str, str] = {
    "critical": "immediate",
    "high": "urgent",
    "medium": "normal",
    "low": "deferred",
}


def classify_tasks(
    tasks: list[dict[str, Any]],
    current_time: str,
) -> dict[str, Any]:
    """Classify each task by type, urgency, and domain.

    Args:
        tasks: Raw task dicts from input.
        current_time: ISO timestamp of current time.

    Returns:
        Structured dict with classified tasks.
    """
    try:
        tasks = copy.deepcopy(tasks)
        classified = []

        for task in tasks:
            task_type = str(task.get("type", "unknown"))
            priority_label = str(task.get("priority", "medium")).lower()
            deadline = task.get("deadline")
            dependencies = list(task.get("dependency", []))

            task_id = f"{task_type}_{uuid.uuid4().hex[:8]}"

            classification = _TYPE_CLASSIFICATION_MAP.get(task_type, "batch")

            if priority_label == "critical" or priority_label == "high":
                if deadline:
                    classification = _promote_classification(classification)

            urgency = _compute_urgency(priority_label, deadline, current_time)
            domain = _DOMAIN_MAP.get(task_type, "general")

            classified.append({
                "task_id": task_id,
                "original_type": task_type,
                "classification": classification,
                "urgency": urgency,
                "domain": domain,
                "deadline": deadline,
                "dependencies": dependencies,
            })

        return {
            "status": "success",
            "classified_tasks": classified,
            "count": len(classified),
        }
    except Exception as exc:
        return {
            "status": "error",
            "classified_tasks": [],
            "count": 0,
            "error": str(exc),
        }


def _promote_classification(classification: str) -> str:
    """Promote a classification to a more urgent type when deadline pressure exists."""
    promotions = {
        "batch": "scheduled",
        "scheduled": "triggered",
        "triggered": "realtime",
        "realtime": "realtime",
    }
    return promotions.get(classification, classification)


def _compute_urgency(
    priority_label: str,
    deadline: str | None,
    current_time: str,
) -> str:
    """Compute urgency from priority label and deadline proximity."""
    base_urgency = _URGENCY_PRIORITY_MAP.get(priority_label, "normal")

    if not deadline or not current_time:
        return base_urgency

    try:
        from datetime import datetime, timezone
        deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        current_dt = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
        hours_remaining = (deadline_dt - current_dt).total_seconds() / 3600.0

        if hours_remaining <= 0:
            return "immediate"
        if hours_remaining <= 2:
            return "immediate"
        if hours_remaining <= 12:
            return "urgent"
        if hours_remaining <= 24:
            if base_urgency == "deferred":
                return "normal"
            return base_urgency
    except (ValueError, TypeError):
        pass

    return base_urgency
