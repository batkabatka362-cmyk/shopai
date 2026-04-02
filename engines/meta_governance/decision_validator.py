"""Meta-Intelligence Governance -- decision validator.

Validates decision quality: logic check, data support,
confidence threshold, consistency with goals.

Model note: Would use Mistral for validation reasoning.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Validation thresholds
# ---------------------------------------------------------------------------

_CONFIDENCE_THRESHOLD = 0.40          # minimum confidence for auto-approval
_MIN_DATA_FIELDS = 2                  # minimum context fields to support a decision
_MAX_BUDGET_WITHOUT_JUSTIFICATION = 200.0  # budget above this needs reasoning

# Expected context fields that support decision quality
_SUPPORTING_DATA_FIELDS = frozenset({
    "daily_budget_limit", "daily_budget_used", "store_status",
    "audience_size", "conversion_rate", "revenue_today",
    "inventory_level", "avg_order_value", "customer_count",
    "campaign_history", "past_performance",
})


def validate_decision(
    activity: dict[str, Any],
    context: dict[str, Any],
    risk_score: float,
    violations: list[dict[str, Any]],
    constraint_enforced: bool,
) -> dict[str, Any]:
    """Validate the quality of the decision being made.

    Args:
        activity: SystemActivity dict from the activity monitor.
        context: Current system context.
        risk_score: Overall risk score from risk controller.
        violations: Rule violations found.
        constraint_enforced: Whether any hard constraint was hit.

    Returns:
        Structured dict with list of ValidationResult dicts and overall pass/fail.
    """
    try:
        activity = copy.deepcopy(activity)
        context = copy.deepcopy(context)

        action = activity.get("action_details", {})
        action_type = activity.get("action_type", "unknown")

        results: list[dict[str, Any]] = []

        results.append(_check_logic(action, action_type, context))
        results.append(_check_data_support(context))
        results.append(_check_confidence(activity, risk_score))
        results.append(_check_goal_consistency(action, action_type, context))
        results.append(_check_proportionality(action, action_type, context))

        all_passed = all(r["passed"] for r in results)
        avg_score = sum(r["score"] for r in results) / len(results) if results else 0.0

        return {
            "status": "success",
            "results": results,
            "all_passed": all_passed,
            "validation_score": round(avg_score, 4),
            "failed_count": sum(1 for r in results if not r["passed"]),
        }
    except Exception as exc:
        return {
            "status": "error",
            "results": [],
            "all_passed": False,
            "validation_score": 0.0,
            "failed_count": 0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Individual validation checks
# ---------------------------------------------------------------------------

def _check_logic(
    action: dict[str, Any],
    action_type: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """VAL-001: Basic logic check — does the action make sense?"""
    score = 1.0
    issues: list[str] = []

    # Budget should be present for spending actions
    spending_actions = {
        "launch_ad", "create_campaign", "set_budget",
        "allocate_budget", "deploy_campaign",
    }
    if action_type in spending_actions:
        budget = action.get("budget")
        if budget is None:
            score -= 0.40
            issues.append("Spending action missing budget field")
        elif float(budget) == 0:
            score -= 0.30
            issues.append("Spending action has zero budget")

    # Platform should be present for ad actions
    ad_actions = {"launch_ad", "create_campaign", "deploy_campaign"}
    if action_type in ad_actions and not action.get("platform"):
        score -= 0.30
        issues.append("Ad action missing platform")

    # Price actions need a price value
    price_actions = {"change_price", "set_discount", "bulk_price_change"}
    if action_type in price_actions:
        if action.get("price") is None and action.get("discount") is None:
            score -= 0.40
            issues.append("Price action missing price or discount value")

    score = max(score, 0.0)
    passed = score >= 0.60

    return {
        "check_name": "logic_check",
        "passed": passed,
        "score": round(score, 4),
        "detail": "; ".join(issues) if issues else "Action logic is sound",
    }


def _check_data_support(context: dict[str, Any]) -> dict[str, Any]:
    """VAL-002: Decision must be supported by sufficient context data."""
    present_fields = [
        f for f in _SUPPORTING_DATA_FIELDS
        if f in context and context[f] is not None
    ]

    count = len(present_fields)
    max_possible = len(_SUPPORTING_DATA_FIELDS)
    score = min(count / max(max_possible * 0.3, 1), 1.0)  # full score at 30% coverage

    passed = count >= _MIN_DATA_FIELDS

    return {
        "check_name": "data_support",
        "passed": passed,
        "score": round(score, 4),
        "detail": (
            f"{count} supporting data fields present ({', '.join(present_fields[:5])})"
            if present_fields
            else "No supporting data fields found in context"
        ),
    }


def _check_confidence(
    activity: dict[str, Any],
    risk_score: float,
) -> dict[str, Any]:
    """VAL-003: Derived confidence must meet threshold.

    Confidence is derived from activity classification and risk score.
    High-risk + execution = lower confidence needed (more scrutiny).
    """
    classification = activity.get("activity_type", "decision")
    severity = activity.get("severity", "medium") if "severity" not in activity else activity.get("severity", "medium")

    # Start with base confidence
    if classification == "learning":
        base = 0.80  # learning actions are inherently safer
    elif classification == "execution":
        base = 0.50
    else:
        base = 0.65

    # Risk lowers confidence
    confidence = base * (1.0 - risk_score * 0.5)
    confidence = round(max(confidence, 0.0), 4)

    passed = confidence >= _CONFIDENCE_THRESHOLD

    return {
        "check_name": "confidence_threshold",
        "passed": passed,
        "score": confidence,
        "detail": (
            f"Confidence {confidence:.2f} {'meets' if passed else 'below'} "
            f"threshold {_CONFIDENCE_THRESHOLD:.2f} "
            f"(base={base:.2f}, risk_penalty={risk_score * 0.5:.2f})"
        ),
    }


def _check_goal_consistency(
    action: dict[str, Any],
    action_type: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """VAL-004: Action should be consistent with business goals."""
    score = 0.70  # default — we can't fully verify without goal data
    issues: list[str] = []

    store_status = str(context.get("store_status", "active")).lower()

    # Spending on an inactive store contradicts goals
    spending_actions = {
        "launch_ad", "create_campaign", "set_budget",
        "allocate_budget", "deploy_campaign",
    }
    if action_type in spending_actions and store_status != "active":
        score -= 0.50
        issues.append("Spending while store is not active contradicts growth goals")

    # Very high spending when revenue is low
    budget = float(action.get("budget", 0))
    revenue_today = float(context.get("revenue_today", 0))
    if budget > 0 and revenue_today > 0 and budget > revenue_today * 2:
        score -= 0.20
        issues.append(
            f"Budget ${budget:.2f} is >2x today's revenue ${revenue_today:.2f}"
        )

    # Discount actions when profit margin is already thin
    if action_type in ("set_discount", "plan_promotion"):
        avg_margin = float(context.get("avg_margin", 0.5))
        if avg_margin < 0.15:
            score -= 0.30
            issues.append(f"Discount action with thin margin ({avg_margin:.0%})")

    score = round(max(score, 0.0), 4)
    passed = score >= 0.40

    return {
        "check_name": "goal_consistency",
        "passed": passed,
        "score": score,
        "detail": "; ".join(issues) if issues else "Action is consistent with inferred goals",
    }


def _check_proportionality(
    action: dict[str, Any],
    action_type: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """VAL-005: Action scale should be proportional to store/business size."""
    score = 0.80  # default — assume proportional unless proven otherwise
    issues: list[str] = []

    budget = float(action.get("budget", 0))

    # Large budget without justification context
    if budget > _MAX_BUDGET_WITHOUT_JUSTIFICATION:
        justification_fields = {"campaign_history", "past_performance", "conversion_rate"}
        has_justification = any(f in context for f in justification_fields)
        if not has_justification:
            score -= 0.25
            issues.append(
                f"Budget ${budget:.2f} > ${_MAX_BUDGET_WITHOUT_JUSTIFICATION:.2f} "
                f"without supporting performance data"
            )

    # Audience size vs budget check
    audience = int(context.get("audience_size", 0))
    if budget > 0 and audience > 0:
        cost_per_person = budget / audience
        if cost_per_person > 5.0:
            score -= 0.20
            issues.append(
                f"Cost per audience member ${cost_per_person:.2f} seems high"
            )

    score = round(max(score, 0.0), 4)
    passed = score >= 0.50

    return {
        "check_name": "proportionality",
        "passed": passed,
        "score": score,
        "detail": "; ".join(issues) if issues else "Action scale is proportional",
    }
