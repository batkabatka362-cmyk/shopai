"""Autonomous Execution Engine — action dispatcher.

Dispatch actions to appropriate tools/handlers based on action type
and target. Validates action structure before dispatch.
"""
from __future__ import annotations

import copy
from typing import Any


_SUPPORTED_TYPES = {"api_call", "db_query", "file_write", "notification", "webhook", "update", "create", "delete"}


def dispatch_actions(
    **kwargs: Any,
) -> dict[str, Any]:
    """Dispatch actions to appropriate handlers.

    Args:
        **kwargs: Must include 'actions' list and 'execution_config' dict.

    Returns:
        Structured dict with dispatch results per action.
    """
    try:
        actions = copy.deepcopy(kwargs.get("actions", []))
        config = kwargs.get("execution_config", {})
        dry_run = config.get("dry_run", False)
        max_retries = int(config.get("max_retries", 3))

        dispatched: list[dict[str, Any]] = []

        for action in actions:
            action_type = str(action.get("type", ""))
            target = str(action.get("target", ""))
            params = action.get("params", {})

            if action_type not in _SUPPORTED_TYPES:
                dispatched.append({
                    "action": action,
                    "status": "skipped",
                    "result": None,
                    "error": f"Unsupported action type: {action_type}",
                })
                continue

            if dry_run:
                dispatched.append({
                    "action": action,
                    "status": "dry_run",
                    "result": {"would_execute": True, "type": action_type, "target": target},
                    "error": None,
                })
                continue

            # Simulate dispatch (in production, this routes to real handlers)
            dispatched.append({
                "action": action,
                "status": "dispatched",
                "result": {
                    "type": action_type,
                    "target": target,
                    "params_count": len(params),
                    "max_retries": max_retries,
                },
                "error": None,
            })

        return {
            "status": "success",
            "result": {
                "dispatched": dispatched,
                "total": len(dispatched),
                "dry_run": dry_run,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Action dispatch failed: {exc}"}
