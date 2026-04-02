"""Meta-Intelligence Governance -- risk controller.

Assesses risk level of the activity across four dimensions:
financial risk, reputation risk, operational risk, compliance risk.

Model note: Would use Mistral for risk assessment logic.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Risk thresholds and weights
# ---------------------------------------------------------------------------

_RISK_WEIGHTS = {
    "financial": 0.35,
    "reputation": 0.25,
    "operational": 0.20,
    "compliance": 0.20,
}

_LEVEL_THRESHOLDS = {
    "low": 0.25,
    "medium": 0.50,
    "high": 0.75,
    # >= 0.75 is critical
}

# Actions with inherently higher risk profiles
_HIGH_FINANCIAL_RISK_ACTIONS = frozenset({
    "launch_ad", "allocate_budget", "set_budget", "deploy_campaign",
    "process_payment", "refund_order",
})

_HIGH_REPUTATION_RISK_ACTIONS = frozenset({
    "publish_content", "send_notification", "schedule_email",
    "deploy_campaign", "launch_ad",
})

_HIGH_OPERATIONAL_RISK_ACTIONS = frozenset({
    "execute_order", "ship_order", "update_inventory",
    "bulk_price_change", "delete_product", "disable_store",
})

_HIGH_COMPLIANCE_RISK_ACTIONS = frozenset({
    "override_safety", "delete_product", "refund_order",
    "bulk_price_change", "disable_store",
})


def assess_risk(
    activity: dict[str, Any],
    context: dict[str, Any],
    violations: list[dict[str, Any]],
    policy_failures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assess risk of the activity across four dimensions.

    Args:
        activity: SystemActivity dict from the activity monitor.
        context: Current system context.
        violations: Rule violations found so far.
        policy_failures: Policy check failures found so far.

    Returns:
        Structured dict with list of RiskAssessment dicts and overall score.
    """
    try:
        activity = copy.deepcopy(activity)
        context = copy.deepcopy(context)

        action = activity.get("action_details", {})
        action_type = activity.get("action_type", "unknown")

        risks: list[dict[str, Any]] = []

        financial = _assess_financial_risk(action, action_type, context, violations)
        risks.append(financial)

        reputation = _assess_reputation_risk(action, action_type, context, policy_failures)
        risks.append(reputation)

        operational = _assess_operational_risk(action, action_type, context)
        risks.append(operational)

        compliance = _assess_compliance_risk(action, action_type, context, violations, policy_failures)
        risks.append(compliance)

        # Compute weighted overall score
        overall_score = sum(
            r["score"] * _RISK_WEIGHTS.get(r["risk_type"], 0.25)
            for r in risks
        )
        overall_score = round(min(overall_score, 1.0), 4)
        overall_level = _score_to_level(overall_score)

        return {
            "status": "success",
            "risks": risks,
            "overall_score": overall_score,
            "overall_level": overall_level,
        }
    except Exception as exc:
        return {
            "status": "error",
            "risks": [],
            "overall_score": 0.5,
            "overall_level": "medium",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Individual risk assessments
# ---------------------------------------------------------------------------

def _assess_financial_risk(
    action: dict[str, Any],
    action_type: str,
    context: dict[str, Any],
    violations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assess financial risk of the action."""
    score = 0.1  # baseline

    budget = float(action.get("budget", 0))
    daily_limit = float(context.get("daily_budget_limit", 0))
    daily_used = float(context.get("daily_budget_used", 0))

    # Higher score for spending actions
    if action_type in _HIGH_FINANCIAL_RISK_ACTIONS:
        score += 0.15

    # Budget magnitude risk
    if budget > 0:
        if budget > 500:
            score += 0.20
        elif budget > 200:
            score += 0.10
        elif budget > 50:
            score += 0.05

    # Daily budget utilization risk
    if daily_limit > 0:
        utilization = (daily_used + budget) / daily_limit
        if utilization > 0.95:
            score += 0.25
        elif utilization > 0.80:
            score += 0.15
        elif utilization > 0.60:
            score += 0.05

    # Budget violations increase financial risk
    budget_violations = [v for v in violations if v.get("field") == "budget"]
    score += len(budget_violations) * 0.10

    score = round(min(score, 1.0), 4)
    detail = _build_financial_detail(budget, daily_limit, daily_used, score)

    return {
        "risk_type": "financial",
        "level": _score_to_level(score),
        "score": score,
        "detail": detail,
    }


def _assess_reputation_risk(
    action: dict[str, Any],
    action_type: str,
    context: dict[str, Any],
    policy_failures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assess reputation risk of the action."""
    score = 0.05  # baseline

    if action_type in _HIGH_REPUTATION_RISK_ACTIONS:
        score += 0.15

    # Content-related risk
    title = str(action.get("title", ""))
    description = str(action.get("description", ""))
    content = str(action.get("content", ""))
    has_content = bool(title or description or content)

    if has_content:
        score += 0.10

    # Content policy failures are a big reputation risk
    content_failures = [
        p for p in policy_failures
        if p.get("policy_name") == "content_policy"
    ]
    score += len(content_failures) * 0.25

    # Sending to a large audience
    audience_size = int(context.get("audience_size", 0))
    if audience_size > 10000:
        score += 0.15
    elif audience_size > 1000:
        score += 0.05

    score = round(min(score, 1.0), 4)

    return {
        "risk_type": "reputation",
        "level": _score_to_level(score),
        "score": score,
        "detail": f"Reputation risk score {score:.2f} for '{action_type}'",
    }


def _assess_operational_risk(
    action: dict[str, Any],
    action_type: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Assess operational risk of the action."""
    score = 0.05  # baseline

    if action_type in _HIGH_OPERATIONAL_RISK_ACTIONS:
        score += 0.20

    # Store status risk
    store_status = str(context.get("store_status", "active")).lower()
    if store_status != "active":
        score += 0.25

    # High-frequency risk
    actions_this_hour = int(context.get("actions_this_hour", 0))
    if actions_this_hour > 40:
        score += 0.20
    elif actions_this_hour > 20:
        score += 0.10

    # Inventory-related risk
    if action_type in ("execute_order", "ship_order"):
        inventory_level = int(context.get("inventory_level", 100))
        if inventory_level < 10:
            score += 0.20
        elif inventory_level < 50:
            score += 0.05

    score = round(min(score, 1.0), 4)

    return {
        "risk_type": "operational",
        "level": _score_to_level(score),
        "score": score,
        "detail": f"Operational risk score {score:.2f} for '{action_type}'",
    }


def _assess_compliance_risk(
    action: dict[str, Any],
    action_type: str,
    context: dict[str, Any],
    violations: list[dict[str, Any]],
    policy_failures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assess compliance risk of the action."""
    score = 0.05  # baseline

    if action_type in _HIGH_COMPLIANCE_RISK_ACTIONS:
        score += 0.20

    # Rule violations increase compliance risk
    critical_violations = [
        v for v in violations if v.get("severity") == "critical"
    ]
    other_violations = [
        v for v in violations if v.get("severity") != "critical"
    ]
    score += len(critical_violations) * 0.20
    score += len(other_violations) * 0.05

    # Policy failures increase compliance risk
    score += len(policy_failures) * 0.10

    # Missing approval for high-impact actions
    approval_failures = [
        p for p in policy_failures
        if p.get("policy_name") == "high_impact_approval"
    ]
    score += len(approval_failures) * 0.20

    score = round(min(score, 1.0), 4)

    return {
        "risk_type": "compliance",
        "level": _score_to_level(score),
        "score": score,
        "detail": f"Compliance risk score {score:.2f} — {len(violations)} violations, {len(policy_failures)} policy failures",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_to_level(score: float) -> str:
    """Convert a 0.0-1.0 risk score to a level string."""
    if score < _LEVEL_THRESHOLDS["low"]:
        return "low"
    if score < _LEVEL_THRESHOLDS["medium"]:
        return "medium"
    if score < _LEVEL_THRESHOLDS["high"]:
        return "high"
    return "critical"


def _build_financial_detail(
    budget: float,
    daily_limit: float,
    daily_used: float,
    score: float,
) -> str:
    """Build a human-readable financial risk detail string."""
    parts = [f"Financial risk score {score:.2f}"]
    if budget > 0:
        parts.append(f"action budget=${budget:.2f}")
    if daily_limit > 0:
        remaining = daily_limit - daily_used
        parts.append(f"daily remaining=${remaining:.2f}/{daily_limit:.2f}")
    return "; ".join(parts)
