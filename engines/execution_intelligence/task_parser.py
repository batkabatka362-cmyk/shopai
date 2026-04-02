"""Execution Intelligence — task parser.

Parses raw action plans into structured individual tasks with normalized fields.
Each action item becomes a ParsedTask with a unique ID, priority, and dependencies.

Model note: Would use Qwen for task structuring and parsing.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any


# Action types and their default priorities (1=highest)
_ACTION_PRIORITIES: dict[str, int] = {
    "create_product": 2,
    "update_product": 2,
    "delete_product": 3,
    "launch_ad": 3,
    "update_ad": 3,
    "stop_ad": 2,
    "update_inventory": 1,
    "set_price": 2,
    "send_email": 4,
    "generate_content": 4,
    "create_discount": 3,
    "update_shipping": 3,
    "create_collection": 3,
    "analyze_performance": 5,
}

# Actions that should run before others when both appear
_DEPENDENCY_RULES: dict[str, list[str]] = {
    "launch_ad": ["create_product"],
    "update_product": ["create_product"],
    "set_price": ["create_product"],
    "send_email": ["generate_content"],
    "update_ad": ["launch_ad"],
    "stop_ad": ["launch_ad"],
}


def parse_action_plan(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse raw action items into structured ParsedTask list.

    Args:
        actions: List of raw action dicts from the decision engine.

    Returns:
        Structured dict with parsed tasks, or error info.
    """
    try:
        if not isinstance(actions, list):
            return {
                "status": "error",
                "tasks": [],
                "error": "Actions must be a list",
            }

        safe_actions = copy.deepcopy(actions)
        parsed_tasks: list[dict[str, Any]] = []
        action_type_to_ids: dict[str, list[str]] = {}
        logs: list[str] = []

        for index, action in enumerate(safe_actions):
            if not isinstance(action, dict):
                logs.append(f"Skipped action at index {index}: not a dict")
                continue

            action_type = _normalize_action_type(action.get("type", ""))
            if not action_type:
                logs.append(f"Skipped action at index {index}: missing or empty type")
                continue

            parameters = action.get("data", {})
            if not isinstance(parameters, dict):
                parameters = {}

            task_id = f"task_{uuid.uuid4().hex[:8]}"
            priority = _resolve_priority(action_type, parameters)
            normalized_params = _normalize_parameters(action_type, parameters)

            task: dict[str, Any] = {
                "task_id": task_id,
                "action_type": action_type,
                "parameters": normalized_params,
                "priority": priority,
                "dependencies": [],
                "source_index": index,
            }

            parsed_tasks.append(task)

            if action_type not in action_type_to_ids:
                action_type_to_ids[action_type] = []
            action_type_to_ids[action_type].append(task_id)

            logs.append(
                f"Parsed action '{action_type}' at index {index} -> {task_id} "
                f"(priority={priority})"
            )

        # Resolve dependencies across tasks in this batch
        _resolve_dependencies(parsed_tasks, action_type_to_ids)

        # Sort by priority (lower number = higher priority)
        parsed_tasks.sort(key=lambda t: t["priority"])

        return {
            "status": "success",
            "tasks": parsed_tasks,
            "count": len(parsed_tasks),
            "skipped": len(safe_actions) - len(parsed_tasks),
            "logs": logs,
        }
    except Exception as exc:
        return {
            "status": "error",
            "tasks": [],
            "count": 0,
            "skipped": 0,
            "logs": [],
            "error": f"Task parsing failed: {exc}",
        }


def _normalize_action_type(raw_type: str) -> str:
    """Normalize action type string: lowercase, strip, replace hyphens.

    Model note: Qwen would handle fuzzy matching of action types.
    """
    if not raw_type or not isinstance(raw_type, str):
        return ""
    normalized = raw_type.strip().lower().replace("-", "_").replace(" ", "_")
    # Remove consecutive underscores
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized


def _resolve_priority(action_type: str, parameters: dict[str, Any]) -> int:
    """Determine task priority from action type and parameters.

    Model note: Qwen would analyze urgency signals in the parameters.
    """
    base_priority = _ACTION_PRIORITIES.get(action_type, 3)

    # Adjust for urgency markers in parameters
    if parameters.get("urgent") is True:
        base_priority = max(1, base_priority - 1)
    if parameters.get("low_priority") is True:
        base_priority = min(5, base_priority + 1)

    return base_priority


def _normalize_parameters(
    action_type: str, parameters: dict[str, Any],
) -> dict[str, Any]:
    """Normalize and enrich parameters based on action type.

    Model note: Qwen would fill in missing defaults intelligently.
    """
    params = copy.deepcopy(parameters)

    if action_type == "create_product":
        params.setdefault("title", "Untitled Product")
        params.setdefault("status", "draft")
        if "price" in params:
            params["price"] = round(float(params["price"]), 2)

    elif action_type == "launch_ad":
        params.setdefault("platform", "facebook")
        params.setdefault("status", "pending")
        if "budget" in params:
            params["budget"] = round(float(params["budget"]), 2)
        params["platform"] = params["platform"].lower().strip()

    elif action_type == "update_inventory":
        if "quantity" in params:
            params["quantity"] = int(params["quantity"])

    elif action_type == "set_price":
        if "price" in params:
            params["price"] = round(float(params["price"]), 2)

    elif action_type == "send_email":
        params.setdefault("subject", "")
        params.setdefault("template", "default")

    elif action_type == "generate_content":
        params.setdefault("content_type", "product_description")
        params.setdefault("tone", "professional")

    elif action_type == "create_discount":
        if "percentage" in params:
            params["percentage"] = min(100.0, max(0.0, float(params["percentage"])))

    return params


def _resolve_dependencies(
    tasks: list[dict[str, Any]],
    action_type_to_ids: dict[str, list[str]],
) -> None:
    """Set dependency task_ids based on ordering rules.

    If a task type depends on another type and both are in the batch,
    add the dependency. Mutates tasks in place.
    """
    for task in tasks:
        dep_types = _DEPENDENCY_RULES.get(task["action_type"], [])
        for dep_type in dep_types:
            dep_ids = action_type_to_ids.get(dep_type, [])
            for dep_id in dep_ids:
                if dep_id != task["task_id"] and dep_id not in task["dependencies"]:
                    task["dependencies"].append(dep_id)
