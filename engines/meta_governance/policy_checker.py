"""Meta-Intelligence Governance — policy checker.

Checks activity against system policies: allowed actions,
time restrictions, spending policies, content policies.

Model note: Would use Mistral for policy interpretation and checking.
"""
from __future__ import annotations

import copy
import time
from typing import Any


# ---------------------------------------------------------------------------
# Policy definitions
# ---------------------------------------------------------------------------

_ALLOWED_PLATFORMS = frozenset({
    "facebook", "google", "instagram", "tiktok", "twitter",
    "pinterest", "linkedin", "snapchat", "youtube",
})

_RESTRICTED_HOURS_UTC = {
    # No high-budget actions between 00:00-06:00 UTC (maintenance window)
    "maintenance_window": (0, 6),
}

_SPENDING_POLICIES = {
    "min_budget_per_ad": 5.0,
    "max_budget_pct_of_daily": 0.50,    # single action can't be >50% of daily limit
    "max_discount_pct": 0.70,           # max 70% discount
}

_CONTENT_POLICIES = {
    "max_title_length": 200,
    "max_description_length": 5000,
    "blocked_keywords": [
        "guaranteed", "miracle", "free money", "get rich",
        "no risk", "100% safe",
    ],
}

# Actions requiring specific approvals
_HIGH_IMPACT_ACTIONS = frozenset({
    "bulk_price_change", "delete_product", "disable_store",
    "refund_order", "override_safety",
})


def check_policies(
    activity: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Check an activity against all system policies.

    Args:
        activity: SystemActivity dict from the activity monitor.
        context: Current system context.

    Returns:
        Structured dict with list of PolicyCheck dicts.
    """
    try:
        activity = copy.deepcopy(activity)
        context = copy.deepcopy(context)

        action = activity.get("action_details", {})
        action_type = activity.get("action_type", "unknown")

        checks: list[dict[str, Any]] = []

        checks.append(_check_platform_policy(action, action_type))
        checks.append(_check_time_restriction_policy(action, action_type))
        checks.append(_check_spending_policy(action, action_type, context))
        checks.append(_check_discount_policy(action))
        checks.append(_check_content_policy(action))
        checks.append(_check_high_impact_policy(action_type, context))

        all_passed = all(c["passed"] for c in checks)

        return {
            "status": "success",
            "checks": checks,
            "all_passed": all_passed,
            "failed_count": sum(1 for c in checks if not c["passed"]),
        }
    except Exception as exc:
        return {
            "status": "error",
            "checks": [],
            "all_passed": False,
            "failed_count": 0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Individual policy checks
# ---------------------------------------------------------------------------

def _check_platform_policy(
    action: dict[str, Any],
    action_type: str,
) -> dict[str, Any]:
    """POL-001: Verify platform is in the allowed list."""
    platform = str(action.get("platform", "")).lower().strip()
    ad_actions = {"launch_ad", "create_campaign", "deploy_campaign"}

    if action_type not in ad_actions or not platform:
        return {
            "policy_id": "POL-001",
            "policy_name": "allowed_platform",
            "passed": True,
            "detail": "Not an ad action or no platform specified — N/A",
        }

    passed = platform in _ALLOWED_PLATFORMS
    return {
        "policy_id": "POL-001",
        "policy_name": "allowed_platform",
        "passed": passed,
        "detail": (
            f"Platform '{platform}' is allowed"
            if passed
            else f"Platform '{platform}' is not in the allowed list"
        ),
    }


def _check_time_restriction_policy(
    action: dict[str, Any],
    action_type: str,
) -> dict[str, Any]:
    """POL-002: Block high-budget actions during maintenance window."""
    current_hour = time.gmtime().tm_hour
    start, end = _RESTRICTED_HOURS_UTC["maintenance_window"]
    in_window = start <= current_hour < end

    budget = float(action.get("budget", 0))
    is_high_budget = budget > 200

    if not in_window or not is_high_budget:
        return {
            "policy_id": "POL-002",
            "policy_name": "time_restriction",
            "passed": True,
            "detail": "Outside maintenance window or low-budget action",
        }

    return {
        "policy_id": "POL-002",
        "policy_name": "time_restriction",
        "passed": False,
        "detail": (
            f"High-budget action (${budget:.2f}) attempted during "
            f"maintenance window ({start}:00-{end}:00 UTC)"
        ),
    }


def _check_spending_policy(
    action: dict[str, Any],
    action_type: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """POL-003: Enforce spending policies."""
    budget = float(action.get("budget", 0))
    daily_limit = float(context.get("daily_budget_limit", 0))

    # Check min budget for ads
    ad_actions = {"launch_ad", "create_campaign", "deploy_campaign"}
    if action_type in ad_actions and 0 < budget < _SPENDING_POLICIES["min_budget_per_ad"]:
        return {
            "policy_id": "POL-003",
            "policy_name": "spending_policy",
            "passed": False,
            "detail": (
                f"Ad budget ${budget:.2f} is below minimum "
                f"${_SPENDING_POLICIES['min_budget_per_ad']:.2f}"
            ),
        }

    # Check max percentage of daily budget
    if daily_limit > 0 and budget > 0:
        pct = budget / daily_limit
        max_pct = _SPENDING_POLICIES["max_budget_pct_of_daily"]
        if pct > max_pct:
            return {
                "policy_id": "POL-003",
                "policy_name": "spending_policy",
                "passed": False,
                "detail": (
                    f"Single action budget ${budget:.2f} is {pct:.0%} of daily limit "
                    f"(max {max_pct:.0%} allowed)"
                ),
            }

    return {
        "policy_id": "POL-003",
        "policy_name": "spending_policy",
        "passed": True,
        "detail": "Spending within policy limits",
    }


def _check_discount_policy(action: dict[str, Any]) -> dict[str, Any]:
    """POL-004: Enforce max discount percentage."""
    discount = action.get("discount")
    if discount is None:
        return {
            "policy_id": "POL-004",
            "policy_name": "discount_policy",
            "passed": True,
            "detail": "No discount in action — N/A",
        }

    discount_val = float(discount)
    max_discount = _SPENDING_POLICIES["max_discount_pct"]
    if discount_val > max_discount:
        return {
            "policy_id": "POL-004",
            "policy_name": "discount_policy",
            "passed": False,
            "detail": (
                f"Discount {discount_val:.0%} exceeds max allowed {max_discount:.0%}"
            ),
        }

    return {
        "policy_id": "POL-004",
        "policy_name": "discount_policy",
        "passed": True,
        "detail": f"Discount {discount_val:.0%} within policy",
    }


def _check_content_policy(action: dict[str, Any]) -> dict[str, Any]:
    """POL-005: Check content against content policies."""
    title = str(action.get("title", ""))
    description = str(action.get("description", ""))
    content = str(action.get("content", ""))
    combined_text = f"{title} {description} {content}".lower()

    # Check for blocked keywords
    for keyword in _CONTENT_POLICIES["blocked_keywords"]:
        if keyword.lower() in combined_text:
            return {
                "policy_id": "POL-005",
                "policy_name": "content_policy",
                "passed": False,
                "detail": f"Content contains blocked keyword: '{keyword}'",
            }

    # Check length limits
    if len(title) > _CONTENT_POLICIES["max_title_length"]:
        return {
            "policy_id": "POL-005",
            "policy_name": "content_policy",
            "passed": False,
            "detail": (
                f"Title length {len(title)} exceeds max "
                f"{_CONTENT_POLICIES['max_title_length']}"
            ),
        }

    return {
        "policy_id": "POL-005",
        "policy_name": "content_policy",
        "passed": True,
        "detail": "Content passes policy checks",
    }


def _check_high_impact_policy(
    action_type: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """POL-006: High-impact actions require explicit approval."""
    if action_type not in _HIGH_IMPACT_ACTIONS:
        return {
            "policy_id": "POL-006",
            "policy_name": "high_impact_approval",
            "passed": True,
            "detail": "Not a high-impact action — N/A",
        }

    has_approval = bool(context.get("explicit_approval", False))
    return {
        "policy_id": "POL-006",
        "policy_name": "high_impact_approval",
        "passed": has_approval,
        "detail": (
            "High-impact action has explicit approval"
            if has_approval
            else f"High-impact action '{action_type}' requires explicit approval"
        ),
    }
