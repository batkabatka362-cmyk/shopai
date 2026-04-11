"""Execution Intelligence — tool selector.

Selects the appropriate tool/API integration for each validated task.
Maps action types to tool configurations.

Model note: Would use Mistral for intelligent tool selection in ambiguous cases.
"""
from __future__ import annotations

import copy
from typing import Any


# Tool registry: action_type -> tool config
_TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "create_product": {
        "tool_name": "shopify_api",
        "endpoint": "products",
        "method": "create",
        "execution_mode": "sync",
    },
    "update_product": {
        "tool_name": "shopify_api",
        "endpoint": "products",
        "method": "update",
        "execution_mode": "sync",
    },
    "delete_product": {
        "tool_name": "shopify_api",
        "endpoint": "products",
        "method": "delete",
        "execution_mode": "sync",
    },
    "launch_ad": {
        "tool_name": "_select_ads_api",  # resolved dynamically
        "endpoint": "campaigns",
        "method": "create",
        "execution_mode": "async",
    },
    "update_ad": {
        "tool_name": "_select_ads_api",
        "endpoint": "campaigns",
        "method": "update",
        "execution_mode": "async",
    },
    "stop_ad": {
        "tool_name": "_select_ads_api",
        "endpoint": "campaigns",
        "method": "pause",
        "execution_mode": "async",
    },
    "update_inventory": {
        "tool_name": "shopify_api",
        "endpoint": "inventory",
        "method": "adjust",
        "execution_mode": "sync",
    },
    "set_price": {
        "tool_name": "shopify_api",
        "endpoint": "variants",
        "method": "update",
        "execution_mode": "sync",
    },
    "send_email": {
        "tool_name": "email_service",
        "endpoint": "messages",
        "method": "send",
        "execution_mode": "async",
    },
    "generate_content": {
        "tool_name": "content_generator",
        "endpoint": "generate",
        "method": "create",
        "execution_mode": "sync",
    },
    "create_discount": {
        "tool_name": "shopify_api",
        "endpoint": "price_rules",
        "method": "create",
        "execution_mode": "sync",
    },
    "update_shipping": {
        "tool_name": "shopify_api",
        "endpoint": "shipping",
        "method": "update",
        "execution_mode": "sync",
    },
    "create_collection": {
        "tool_name": "shopify_api",
        "endpoint": "collections",
        "method": "create",
        "execution_mode": "sync",
    },
    "analyze_performance": {
        "tool_name": "shopify_api",
        "endpoint": "analytics",
        "method": "query",
        "execution_mode": "sync",
    },
}


def select_tools(validated_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Select appropriate tools for each validated task.

    Args:
        validated_tasks: List of ValidatedTask dicts (only valid ones).

    Returns:
        Structured dict with tool selections per task.
    """
    try:
        if not isinstance(validated_tasks, list):
            return {
                "status": "error",
                "selections": [],
                "error": "Validated tasks must be a list",
            }

        safe_tasks = copy.deepcopy(validated_tasks)
        selections: list[dict[str, Any]] = []
        logs: list[str] = []

        for task in safe_tasks:
            task_id = task.get("task_id", "unknown")
            action_type = task.get("action_type", "")
            parameters = task.get("parameters", {})

            selection = _select_tool_for_task(task_id, action_type, parameters)
            selections.append(selection)

            logs.append(
                f"Tool selected for {task_id} ({action_type}): "
                f"{selection['tool_name']} [{selection['execution_mode']}]"
            )

        return {
            "status": "success",
            "selections": selections,
            "count": len(selections),
            "logs": logs,
        }
    except Exception as exc:
        return {
            "status": "error",
            "selections": [],
            "count": 0,
            "logs": [],
            "error": f"Tool selection failed: {exc}",
        }


def _select_tool_for_task(
    task_id: str,
    action_type: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Select the right tool for a single task.

    Model note: Mistral would handle ambiguous tool selection.
    """
    registry_entry = _TOOL_REGISTRY.get(action_type)

    if registry_entry is None:
        return {
            "task_id": task_id,
            "action_type": action_type,
            "tool_name": "unknown",
            "tool_config": {},
            "execution_mode": "sync",
        }

    tool_name = registry_entry["tool_name"]
    execution_mode = registry_entry["execution_mode"]

    # Dynamic resolution for ad platforms
    if tool_name == "_select_ads_api":
        tool_name = _resolve_ads_api(parameters)

    tool_config: dict[str, Any] = {
        "endpoint": registry_entry["endpoint"],
        "method": registry_entry["method"],
    }

    # Add content generator model hint
    if tool_name == "content_generator":
        tool_config["model_hint"] = "llama"
        content_type = parameters.get("content_type", "product_description")
        tool_config["content_type"] = content_type

    return {
        "task_id": task_id,
        "action_type": action_type,
        "tool_name": tool_name,
        "tool_config": tool_config,
        "execution_mode": execution_mode,
    }


def _resolve_ads_api(parameters: dict[str, Any]) -> str:
    """Select the correct ads API based on platform parameter."""
    platform = str(parameters.get("platform", "facebook")).lower().strip()

    platform_to_api: dict[str, str] = {
        "facebook": "facebook_ads",
        "instagram": "facebook_ads",  # Instagram ads go through Facebook
        "google": "google_ads",
        "tiktok": "tiktok_ads",
        "pinterest": "pinterest_ads",
    }

    return platform_to_api.get(platform, "facebook_ads")
