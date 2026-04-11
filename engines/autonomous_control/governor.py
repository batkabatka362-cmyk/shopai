"""Autonomous Control Engine — governor.

Governs execution rate and scope to prevent runaway autonomous operations.
"""
from __future__ import annotations

import copy
from typing import Any


def govern_execution(
    actions: list[dict[str, Any]],
    safety_limits: dict[str, Any],
    resource_usage: dict[str, Any],
) -> dict[str, Any]:
    """Apply rate/scope governance to actions.

    Args:
        actions: List of ActionItem dicts.
        safety_limits: SafetyLimits dict.
        resource_usage: Current resource usage from resource_monitor.

    Returns:
        Structured dict with governor decisions per action.
    """
    try:
        items = copy.deepcopy(actions)
        max_per_minute = int(safety_limits.get("max_actions_per_minute", 60))
        within_budget = resource_usage.get("within_budget", True)

        decisions: list[dict[str, Any]] = []
        action_count = len(items)

        for idx, action in enumerate(items):
            action_id = str(action.get("id", "unknown"))
            allowed = True
            throttled = False
            delay_seconds = 0.0
            reason = "Approved by governor"

            if action_count > max_per_minute:
                if idx >= max_per_minute:
                    allowed = False
                    reason = f"Rate limit exceeded ({max_per_minute}/min)"
                elif idx >= max_per_minute * 0.8:
                    throttled = True
                    delay_seconds = round((idx - max_per_minute * 0.8) * 0.5, 1)
                    reason = "Approaching rate limit, throttled"

            if not within_budget:
                throttled = True
                delay_seconds = max(delay_seconds, 2.0)
                reason = "Resource budget pressure, throttled"

            decisions.append({
                "action_id": action_id,
                "allowed": allowed,
                "throttled": throttled,
                "delay_seconds": delay_seconds,
                "reason": reason,
            })

        return {"status": "success", "decisions": decisions}
    except Exception as exc:
        return {"status": "error", "decisions": [], "error": f"Governor failed: {exc}"}
