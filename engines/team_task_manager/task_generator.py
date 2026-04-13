"""Team Task Manager Engine — task generator.

Generates actionable tasks from pending engine outputs and actions.
Each task gets a unique ID, description, and estimated effort.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any


def generate_tasks(
    pending_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate structured tasks from pending action items.

    Converts raw pending actions into standardized task objects with
    IDs, descriptions, categories, and effort estimates.

    Args:
        pending_actions: List of action dicts with source_engine,
            action_type, description, urgency, estimated_minutes fields.

    Returns:
        Structured dict with tasks list.
    """
    try:
        actions = copy.deepcopy(pending_actions)
        tasks: list[dict[str, Any]] = []

        for idx, action in enumerate(actions):
            source = str(action.get("source_engine", "unknown"))
            action_type = str(action.get("action_type", "general"))
            description = str(action.get("description", ""))
            urgency = str(action.get("urgency", "medium"))
            estimated_minutes = int(action.get("estimated_minutes", 30))

            if not description:
                continue

            # Generate deterministic task ID from content
            hash_input = f"{source}:{action_type}:{description}:{idx}"
            task_id = "TSK-" + hashlib.sha256(
                hash_input.encode(),
            ).hexdigest()[:8].upper()

            # Categorize task
            category = _categorize(action_type, source)

            tasks.append({
                "id": task_id,
                "source_engine": source,
                "action_type": action_type,
                "category": category,
                "description": description,
                "urgency": urgency,
                "estimated_minutes": estimated_minutes,
                "status": "pending",
            })

        return {
            "status": "success",
            "tasks": tasks,
            "total_tasks": len(tasks),
        }
    except Exception as exc:
        return {
            "status": "error",
            "tasks": [],
            "error": f"Task generation failed: {exc}",
        }


def _categorize(action_type: str, source: str) -> str:
    """Categorize a task based on its type and source engine."""
    inventory_keywords = {"reorder", "stock", "inventory", "supplier"}
    marketing_keywords = {"campaign", "email", "social", "content", "ad"}
    support_keywords = {"support", "ticket", "customer", "review"}
    ops_keywords = {"shipping", "order", "fulfillment", "returns"}

    combined = f"{action_type} {source}".lower()

    if any(kw in combined for kw in inventory_keywords):
        return "inventory"
    if any(kw in combined for kw in marketing_keywords):
        return "marketing"
    if any(kw in combined for kw in support_keywords):
        return "customer_support"
    if any(kw in combined for kw in ops_keywords):
        return "operations"
    return "general"
