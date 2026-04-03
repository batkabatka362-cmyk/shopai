"""Autonomous Control Engine — rollback manager.

Creates rollback checkpoints for reversible actions.
Determines which actions can be rolled back and how.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any


# Action types that support rollback
_REVERSIBLE_TYPES = {
    "price_change", "inventory_update", "listing_update",
    "campaign_toggle", "setting_change", "discount_apply",
}


def create_rollback_points(
    actions: list[dict[str, Any]],
    safety_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create rollback checkpoints for approved actions.

    Args:
        actions: List of ActionItem dicts.
        safety_results: Safety check results per action.

    Returns:
        Structured dict with rollback points.
    """
    try:
        items = copy.deepcopy(actions)
        safe_map = {
            r.get("action_id", ""): r for r in safety_results
        }

        rollback_points: list[dict[str, Any]] = []

        for action in items:
            action_id = str(action.get("id", "unknown"))
            action_type = str(action.get("type", ""))
            params = action.get("params", {})

            # Only create rollback points for safe actions
            safety = safe_map.get(action_id, {})
            if not safety.get("safe", False):
                continue

            reversible = action_type in _REVERSIBLE_TYPES
            rollback_steps = _build_rollback_steps(action_type, params)

            rollback_points.append({
                "action_id": action_id,
                "checkpoint_id": uuid.uuid4().hex[:10],
                "reversible": reversible,
                "rollback_steps": rollback_steps,
            })

        return {
            "status": "success",
            "rollback_points": rollback_points,
        }
    except Exception as exc:
        return {
            "status": "error",
            "rollback_points": [],
            "error": f"Rollback management failed: {exc}",
        }


def _build_rollback_steps(
    action_type: str,
    params: dict[str, Any],
) -> list[str]:
    """Build the list of steps needed to reverse an action."""
    if action_type not in _REVERSIBLE_TYPES:
        return ["Manual intervention required — action is not auto-reversible"]

    target = str(params.get("target", "unknown"))
    steps = {
        "price_change": [
            f"Restore original price on {target}",
            "Verify price propagated to all channels",
        ],
        "inventory_update": [
            f"Restore previous stock level on {target}",
            "Recalculate availability across warehouses",
        ],
        "listing_update": [
            f"Revert listing content on {target}",
            "Clear CDN cache for listing images",
        ],
        "campaign_toggle": [
            f"Revert campaign state on {target}",
            "Verify ad spend paused/resumed",
        ],
        "setting_change": [
            f"Restore previous setting value on {target}",
        ],
        "discount_apply": [
            f"Remove discount from {target}",
            "Verify cart prices updated",
        ],
    }
    return steps.get(action_type, ["No rollback steps defined"])
