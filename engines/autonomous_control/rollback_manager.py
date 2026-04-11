"""Autonomous Control Engine — rollback manager.

Creates rollback points for approved actions so they can be undone.
"""
from __future__ import annotations

import copy
import time
import uuid
from typing import Any


def create_rollback_points(
    approved_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create rollback checkpoints for each approved action.

    Args:
        approved_actions: List of actions that passed safety checks.

    Returns:
        Structured dict with rollback points.
    """
    try:
        items = copy.deepcopy(approved_actions)
        rollback_points: list[dict[str, Any]] = []

        for action in items:
            action_id = str(action.get("id", action.get("action_id", "unknown")))
            rollback_points.append({
                "id": uuid.uuid4().hex[:12],
                "action_id": action_id,
                "snapshot": {
                    "action_type": action.get("type", ""),
                    "target": action.get("target", ""),
                    "params": action.get("params", {}),
                },
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })

        return {"status": "success", "rollback_points": rollback_points}
    except Exception as exc:
        return {"status": "error", "rollback_points": [], "error": f"Rollback creation failed: {exc}"}
