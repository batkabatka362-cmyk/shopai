"""Autonomous Control Engine — governor.

Governs execution rate and scope. Applies throttling to prevent
system overload and ensures actions are dispatched at safe intervals.
"""
from __future__ import annotations

import copy
from typing import Any


# Max actions per minute by risk level
_RATE_LIMITS = {
    "low": 60,
    "medium": 20,
    "high": 5,
    "critical": 1,
}


def govern_execution(
    actions: list[dict[str, Any]],
    safety_results: list[dict[str, Any]],
    safety_limits: dict[str, Any],
    resource_usage: dict[str, Any],
) -> dict[str, Any]:
    """Apply rate/scope governance to actions.

    Args:
        actions: List of ActionItem dicts.
        safety_results: Safety check results per action.
        safety_limits: SafetyLimits configuration.
        resource_usage: Current resource usage.

    Returns:
        Structured dict with governor decisions per action.
    """
    try:
        items = copy.deepcopy(actions)
        safe_map = {r.get("action_id", ""): r for r in safety_results}

        max_per_min = int(safety_limits.get("max_actions_per_minute", 30))
        headroom = float(resource_usage.get("headroom_pct", 100.0))

        decisions: list[dict[str, Any]] = []
        actions_this_minute = 0

        for action in items:
            action_id = str(action.get("id", "unknown"))
            risk_level = str(action.get("risk_level", "low"))

            safety = safe_map.get(action_id, {})
            if not safety.get("safe", False):
                decisions.append({
                    "action_id": action_id,
                    "allowed": False,
                    "throttled": False,
                    "delay_seconds": 0.0,
                    "reason": "Blocked by safety checker",
                })
                continue

            rate_limit = _RATE_LIMITS.get(risk_level, 30)
            effective_limit = min(rate_limit, max_per_min)

            actions_this_minute += 1
            throttled = False
            delay = 0.0
            reason = "approved"

            # Throttle if approaching rate limit
            if actions_this_minute > effective_limit:
                throttled = True
                delay = 60.0 / effective_limit
                reason = f"Throttled: {actions_this_minute}/{effective_limit} per minute"

            # Throttle if low resource headroom
            if headroom < 20.0:
                throttled = True
                delay = max(delay, 5.0)
                reason = f"Low resource headroom ({headroom:.1f}%)"

            # Block if no headroom
            if headroom <= 0:
                decisions.append({
                    "action_id": action_id,
                    "allowed": False,
                    "throttled": False,
                    "delay_seconds": 0.0,
                    "reason": "Resource budget exhausted",
                })
                continue

            decisions.append({
                "action_id": action_id,
                "allowed": True,
                "throttled": throttled,
                "delay_seconds": round(delay, 1),
                "reason": reason,
            })

        return {
            "status": "success",
            "decisions": decisions,
        }
    except Exception as exc:
        return {
            "status": "error",
            "decisions": [],
            "error": f"Governor failed: {exc}",
        }
