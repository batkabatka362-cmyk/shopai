"""Meta-Intelligence Governance -- constraint enforcer.

Enforces hard constraints that cannot be overridden:
max budget per day, max actions per hour, required approvals, cooldown periods.

These are absolute limits — unlike rules (which can warn), constraints block.

Model note: Pure rule-based enforcement — no model needed.
"""
from __future__ import annotations

import copy
import time
from typing import Any


# ---------------------------------------------------------------------------
# Hard constraint definitions
# ---------------------------------------------------------------------------

_CONSTRAINTS = {
    "max_daily_budget": {
        "constraint_id": "CON-001",
        "constraint_name": "max_daily_budget",
        "description": "Total daily spend must not exceed daily budget limit",
    },
    "max_actions_per_hour": {
        "constraint_id": "CON-002",
        "constraint_name": "max_actions_per_hour",
        "limit": 60,
        "description": "Hard cap of 60 actions per hour per engine",
    },
    "required_approval_high_impact": {
        "constraint_id": "CON-003",
        "constraint_name": "required_approval_high_impact",
        "description": "High-impact actions require explicit approval flag",
    },
    "cooldown_same_action": {
        "constraint_id": "CON-004",
        "constraint_name": "cooldown_same_action",
        "min_seconds": 60,
        "description": "Same action type must have at least 60s cooldown",
    },
    "max_single_spend": {
        "constraint_id": "CON-005",
        "constraint_name": "max_single_spend",
        "limit": 2000.0,
        "description": "Absolute hard cap of $2000 for any single action",
    },
}

# Actions that require explicit approval
_APPROVAL_REQUIRED_ACTIONS = frozenset({
    "bulk_price_change", "delete_product", "disable_store",
    "refund_order", "override_safety",
})

# Actions that spend money
_SPENDING_ACTIONS = frozenset({
    "launch_ad", "create_campaign", "set_budget", "allocate_budget",
    "deploy_campaign", "schedule_email", "process_payment",
})


def enforce_constraints(
    activity: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Enforce hard constraints on the activity.

    Args:
        activity: SystemActivity dict from the activity monitor.
        context: Current system context.

    Returns:
        Structured dict with list of ConstraintResult dicts.
    """
    try:
        activity = copy.deepcopy(activity)
        context = copy.deepcopy(context)

        action = activity.get("action_details", {})
        action_type = activity.get("action_type", "unknown")

        results: list[dict[str, Any]] = []

        results.append(_check_daily_budget(action, action_type, context))
        results.append(_check_actions_per_hour(context))
        results.append(_check_required_approval(action_type, context))
        results.append(_check_cooldown(action_type, context))
        results.append(_check_max_single_spend(action, action_type))

        any_enforced = any(r["enforced"] for r in results)

        return {
            "status": "success",
            "results": results,
            "any_enforced": any_enforced,
            "enforced_count": sum(1 for r in results if r["enforced"]),
        }
    except Exception as exc:
        return {
            "status": "error",
            "results": [],
            "any_enforced": True,  # fail-safe: assume constraints hit on error
            "enforced_count": 0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Individual constraint checks
# ---------------------------------------------------------------------------

def _check_daily_budget(
    action: dict[str, Any],
    action_type: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """CON-001: Total daily spend must not exceed daily budget limit."""
    con = _CONSTRAINTS["max_daily_budget"]
    budget = float(action.get("budget", 0))
    daily_limit = float(context.get("daily_budget_limit", 0))
    daily_used = float(context.get("daily_budget_used", 0))

    if action_type not in _SPENDING_ACTIONS or budget <= 0:
        return {
            "constraint_id": con["constraint_id"],
            "constraint_name": con["constraint_name"],
            "enforced": False,
            "detail": "Non-spending action or zero budget — N/A",
            "limit_value": daily_limit,
            "actual_value": daily_used,
        }

    if daily_limit <= 0:
        return {
            "constraint_id": con["constraint_id"],
            "constraint_name": con["constraint_name"],
            "enforced": False,
            "detail": "No daily budget limit configured",
            "limit_value": 0,
            "actual_value": daily_used,
        }

    total_after = daily_used + budget
    enforced = total_after > daily_limit

    return {
        "constraint_id": con["constraint_id"],
        "constraint_name": con["constraint_name"],
        "enforced": enforced,
        "detail": (
            f"Would exceed daily budget: ${daily_used:.2f} + ${budget:.2f} = "
            f"${total_after:.2f} > limit ${daily_limit:.2f}"
            if enforced
            else f"Within daily budget: ${total_after:.2f} / ${daily_limit:.2f}"
        ),
        "limit_value": daily_limit,
        "actual_value": total_after,
    }


def _check_actions_per_hour(context: dict[str, Any]) -> dict[str, Any]:
    """CON-002: Hard cap on actions per hour."""
    con = _CONSTRAINTS["max_actions_per_hour"]
    actions_this_hour = int(context.get("actions_this_hour", 0))
    limit = con["limit"]

    enforced = actions_this_hour >= limit

    return {
        "constraint_id": con["constraint_id"],
        "constraint_name": con["constraint_name"],
        "enforced": enforced,
        "detail": (
            f"Hourly action limit reached: {actions_this_hour} >= {limit}"
            if enforced
            else f"Within hourly limit: {actions_this_hour} / {limit}"
        ),
        "limit_value": limit,
        "actual_value": actions_this_hour,
    }


def _check_required_approval(
    action_type: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """CON-003: High-impact actions need explicit approval."""
    con = _CONSTRAINTS["required_approval_high_impact"]

    if action_type not in _APPROVAL_REQUIRED_ACTIONS:
        return {
            "constraint_id": con["constraint_id"],
            "constraint_name": con["constraint_name"],
            "enforced": False,
            "detail": "Not a high-impact action — N/A",
            "limit_value": "approval_required",
            "actual_value": "not_applicable",
        }

    has_approval = bool(context.get("explicit_approval", False))
    enforced = not has_approval

    return {
        "constraint_id": con["constraint_id"],
        "constraint_name": con["constraint_name"],
        "enforced": enforced,
        "detail": (
            f"High-impact action '{action_type}' missing required approval"
            if enforced
            else f"High-impact action '{action_type}' has required approval"
        ),
        "limit_value": "approval_required",
        "actual_value": "approved" if has_approval else "not_approved",
    }


def _check_cooldown(
    action_type: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """CON-004: Same action type must have cooldown between executions."""
    con = _CONSTRAINTS["cooldown_same_action"]
    min_seconds = con["min_seconds"]

    last_same_action_ts = context.get("last_same_action_timestamp")
    if not last_same_action_ts:
        return {
            "constraint_id": con["constraint_id"],
            "constraint_name": con["constraint_name"],
            "enforced": False,
            "detail": "No previous execution of this action type recorded",
            "limit_value": min_seconds,
            "actual_value": None,
        }

    try:
        last_ts = float(last_same_action_ts)
        elapsed = time.time() - last_ts
        enforced = elapsed < min_seconds
    except (TypeError, ValueError):
        # If the timestamp is an ISO string, try parsing it
        try:
            import datetime
            dt = datetime.datetime.fromisoformat(str(last_same_action_ts).replace("Z", "+00:00"))
            elapsed = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds()
            enforced = elapsed < min_seconds
        except Exception:
            elapsed = 0.0
            enforced = False

    return {
        "constraint_id": con["constraint_id"],
        "constraint_name": con["constraint_name"],
        "enforced": enforced,
        "detail": (
            f"Cooldown not met: {elapsed:.0f}s elapsed, minimum {min_seconds}s required"
            if enforced
            else f"Cooldown satisfied: {elapsed:.0f}s elapsed (min {min_seconds}s)"
        ),
        "limit_value": min_seconds,
        "actual_value": round(elapsed, 1),
    }


def _check_max_single_spend(
    action: dict[str, Any],
    action_type: str,
) -> dict[str, Any]:
    """CON-005: Absolute hard cap on single action spend."""
    con = _CONSTRAINTS["max_single_spend"]
    budget = float(action.get("budget", 0))
    limit = con["limit"]

    if action_type not in _SPENDING_ACTIONS or budget <= 0:
        return {
            "constraint_id": con["constraint_id"],
            "constraint_name": con["constraint_name"],
            "enforced": False,
            "detail": "Non-spending action or zero budget — N/A",
            "limit_value": limit,
            "actual_value": budget,
        }

    enforced = budget > limit

    return {
        "constraint_id": con["constraint_id"],
        "constraint_name": con["constraint_name"],
        "enforced": enforced,
        "detail": (
            f"Single action spend ${budget:.2f} exceeds hard cap ${limit:.2f}"
            if enforced
            else f"Single action spend ${budget:.2f} within cap ${limit:.2f}"
        ),
        "limit_value": limit,
        "actual_value": budget,
    }
