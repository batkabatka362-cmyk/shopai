"""Autonomous Control Engine — safety checker.

Verifies each action is within safety bounds: allowed types,
forbidden targets, and risk-level classification.
"""
from __future__ import annotations

import copy
from typing import Any


def check_safety(
    actions: list[dict[str, Any]],
    safety_limits: dict[str, Any],
) -> dict[str, Any]:
    """Check each action against safety limits.

    Args:
        actions: List of ActionItem dicts.
        safety_limits: SafetyLimits dict.

    Returns:
        Structured dict with per-action safety results.
    """
    try:
        items = copy.deepcopy(actions)
        allowed_types = safety_limits.get("allowed_action_types", [])
        forbidden_targets = safety_limits.get("forbidden_targets", [])

        results: list[dict[str, Any]] = []

        for action in items:
            action_id = str(action.get("id", "unknown"))
            action_type = str(action.get("type", ""))
            target = str(action.get("target", ""))

            safe = True
            reason = "Within safety bounds"
            risk_level = "low"

            if allowed_types and action_type not in allowed_types:
                safe = False
                reason = f"Action type '{action_type}' not in allowed types"
                risk_level = "high"
            elif target in forbidden_targets:
                safe = False
                reason = f"Target '{target}' is forbidden"
                risk_level = "critical"
            else:
                if action_type in ("delete", "drop", "destroy"):
                    risk_level = "high"
                elif action_type in ("update", "modify", "write"):
                    risk_level = "medium"

            results.append({
                "action_id": action_id,
                "action_type": action_type,
                "safe": safe,
                "reason": reason,
                "risk_level": risk_level,
            })

        return {"status": "success", "checks": results}
    except Exception as exc:
        return {"status": "error", "checks": [], "error": f"Safety check failed: {exc}"}
