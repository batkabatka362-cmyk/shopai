"""Meta-Intelligence Governance — rule engine.

Checks activity against defined rules: budget limits, frequency limits,
action restrictions, and domain rules.

Model note: Would use Mistral for rule checking and validation logic.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Rule definitions — each rule is a callable that returns violations
# ---------------------------------------------------------------------------

_BUDGET_RULES = {
    "max_single_action_budget": {
        "rule_id": "BUD-001",
        "rule_name": "max_single_action_budget",
        "limit": 1000.0,
        "description": "No single action may exceed $1000 budget",
    },
    "daily_budget_headroom": {
        "rule_id": "BUD-002",
        "rule_name": "daily_budget_headroom",
        "min_remaining_pct": 0.10,
        "description": "At least 10% of daily budget must remain after action",
    },
    "budget_must_be_positive": {
        "rule_id": "BUD-003",
        "rule_name": "budget_must_be_positive",
        "description": "Budget values must be positive",
    },
}

_FREQUENCY_RULES = {
    "max_actions_per_hour": {
        "rule_id": "FRQ-001",
        "rule_name": "max_actions_per_hour",
        "limit": 50,
        "description": "Max 50 actions per hour per engine",
    },
    "max_same_action_per_day": {
        "rule_id": "FRQ-002",
        "rule_name": "max_same_action_per_day",
        "limit": 10,
        "description": "Same action type max 10 times per day",
    },
}

_ACTION_RESTRICTIONS = {
    "no_action_on_inactive_store": {
        "rule_id": "ACT-001",
        "rule_name": "no_action_on_inactive_store",
        "description": "No spending actions on inactive stores",
    },
    "no_negative_discount": {
        "rule_id": "ACT-002",
        "rule_name": "no_negative_discount",
        "description": "Discount values must not be negative",
    },
    "platform_must_be_specified": {
        "rule_id": "ACT-003",
        "rule_name": "platform_must_be_specified",
        "description": "Ad actions must specify a platform",
    },
}

# Action types that spend money
_SPENDING_ACTIONS = frozenset({
    "launch_ad", "create_campaign", "set_budget", "allocate_budget",
    "deploy_campaign", "schedule_email",
})


def check_rules(
    activity: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Check an activity against all governance rules.

    Args:
        activity: SystemActivity dict from the activity monitor.
        context: Current system context.

    Returns:
        Structured dict with list of RuleViolation dicts.
    """
    try:
        activity = copy.deepcopy(activity)
        context = copy.deepcopy(context)

        action = activity.get("action_details", {})
        action_type = activity.get("action_type", "unknown")

        violations: list[dict[str, Any]] = []

        # --- Budget rules ---
        violations.extend(_check_budget_rules(action, action_type, context))

        # --- Frequency rules ---
        violations.extend(_check_frequency_rules(activity, context))

        # --- Action restriction rules ---
        violations.extend(_check_action_restrictions(action, action_type, context))

        return {
            "status": "success",
            "violations": violations,
            "violation_count": len(violations),
            "has_critical": any(v["severity"] == "critical" for v in violations),
        }
    except Exception as exc:
        return {
            "status": "error",
            "violations": [],
            "violation_count": 0,
            "has_critical": False,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Budget rule checks
# ---------------------------------------------------------------------------

def _check_budget_rules(
    action: dict[str, Any],
    action_type: str,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check budget-related rules."""
    violations: list[dict[str, Any]] = []
    budget = float(action.get("budget", 0))

    # BUD-001: max single action budget
    rule = _BUDGET_RULES["max_single_action_budget"]
    if budget > rule["limit"]:
        violations.append({
            "rule_id": rule["rule_id"],
            "rule_name": rule["rule_name"],
            "severity": "critical",
            "detail": f"Action budget ${budget:.2f} exceeds max ${rule['limit']:.2f}",
            "field": "budget",
        })

    # BUD-002: daily budget headroom
    if action_type in _SPENDING_ACTIONS and budget > 0:
        rule = _BUDGET_RULES["daily_budget_headroom"]
        daily_limit = float(context.get("daily_budget_limit", 0))
        daily_used = float(context.get("daily_budget_used", 0))

        if daily_limit > 0:
            remaining_after = daily_limit - daily_used - budget
            remaining_pct = remaining_after / daily_limit

            if remaining_after < 0:
                violations.append({
                    "rule_id": rule["rule_id"],
                    "rule_name": rule["rule_name"],
                    "severity": "critical",
                    "detail": (
                        f"Action would exceed daily budget: "
                        f"used=${daily_used:.2f} + action=${budget:.2f} "
                        f"> limit=${daily_limit:.2f}"
                    ),
                    "field": "budget",
                })
            elif remaining_pct < rule["min_remaining_pct"]:
                violations.append({
                    "rule_id": rule["rule_id"],
                    "rule_name": rule["rule_name"],
                    "severity": "warning",
                    "detail": (
                        f"After action only {remaining_pct:.1%} of daily budget remains "
                        f"(min {rule['min_remaining_pct']:.0%} recommended)"
                    ),
                    "field": "budget",
                })

    # BUD-003: budget must be positive
    if action_type in _SPENDING_ACTIONS:
        rule = _BUDGET_RULES["budget_must_be_positive"]
        if budget < 0:
            violations.append({
                "rule_id": rule["rule_id"],
                "rule_name": rule["rule_name"],
                "severity": "violation",
                "detail": f"Budget is negative: ${budget:.2f}",
                "field": "budget",
            })

    return violations


# ---------------------------------------------------------------------------
# Frequency rule checks
# ---------------------------------------------------------------------------

def _check_frequency_rules(
    activity: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check frequency-related rules."""
    violations: list[dict[str, Any]] = []

    # FRQ-001: max actions per hour
    rule = _FREQUENCY_RULES["max_actions_per_hour"]
    actions_this_hour = int(context.get("actions_this_hour", 0))
    if actions_this_hour >= rule["limit"]:
        violations.append({
            "rule_id": rule["rule_id"],
            "rule_name": rule["rule_name"],
            "severity": "violation",
            "detail": (
                f"Engine has performed {actions_this_hour} actions this hour "
                f"(limit: {rule['limit']})"
            ),
            "field": "frequency",
        })

    # FRQ-002: max same action per day
    rule = _FREQUENCY_RULES["max_same_action_per_day"]
    action_type = activity.get("action_type", "unknown")
    same_action_today = int(context.get("same_action_count_today", 0))
    if same_action_today >= rule["limit"]:
        violations.append({
            "rule_id": rule["rule_id"],
            "rule_name": rule["rule_name"],
            "severity": "warning",
            "detail": (
                f"Action '{action_type}' has been performed {same_action_today} "
                f"times today (limit: {rule['limit']})"
            ),
            "field": "frequency",
        })

    return violations


# ---------------------------------------------------------------------------
# Action restriction checks
# ---------------------------------------------------------------------------

def _check_action_restrictions(
    action: dict[str, Any],
    action_type: str,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check action restriction rules."""
    violations: list[dict[str, Any]] = []

    # ACT-001: no spending on inactive store
    rule = _ACTION_RESTRICTIONS["no_action_on_inactive_store"]
    store_status = str(context.get("store_status", "active")).lower()
    if action_type in _SPENDING_ACTIONS and store_status != "active":
        violations.append({
            "rule_id": rule["rule_id"],
            "rule_name": rule["rule_name"],
            "severity": "critical",
            "detail": f"Spending action '{action_type}' attempted on {store_status} store",
            "field": "store_status",
        })

    # ACT-002: no negative discount
    rule = _ACTION_RESTRICTIONS["no_negative_discount"]
    discount = action.get("discount")
    if discount is not None and float(discount) < 0:
        violations.append({
            "rule_id": rule["rule_id"],
            "rule_name": rule["rule_name"],
            "severity": "violation",
            "detail": f"Discount value is negative: {discount}",
            "field": "discount",
        })

    # ACT-003: platform must be specified for ad actions
    rule = _ACTION_RESTRICTIONS["platform_must_be_specified"]
    ad_actions = {"launch_ad", "create_campaign", "deploy_campaign"}
    if action_type in ad_actions and not action.get("platform"):
        violations.append({
            "rule_id": rule["rule_id"],
            "rule_name": rule["rule_name"],
            "severity": "violation",
            "detail": f"Ad action '{action_type}' missing required platform field",
            "field": "platform",
        })

    return violations
