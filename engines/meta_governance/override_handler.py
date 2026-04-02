"""Meta-Intelligence Governance -- override handler.

Handles cases where governance wants to reject or modify an action.
Determines if an override is needed and applies modifications.

Model note: Would use LLaMA for high-level reasoning on complex overrides.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Override thresholds
# ---------------------------------------------------------------------------

_REJECT_IF_RISK_ABOVE = 0.80
_MODIFY_IF_RISK_ABOVE = 0.50
_BUDGET_REDUCTION_FACTOR = 0.70  # reduce to 70% of original if modified


def handle_override(
    activity: dict[str, Any],
    context: dict[str, Any],
    violations: list[dict[str, Any]],
    policy_failures: list[dict[str, Any]],
    risk_score: float,
    risk_level: str,
    constraint_enforced: bool,
    validation_passed: bool,
    validation_score: float,
) -> dict[str, Any]:
    """Determine if an override is needed and what modifications to apply.

    Args:
        activity: SystemActivity dict.
        context: Current system context.
        violations: Rule violations found.
        policy_failures: Failed policy checks.
        risk_score: Overall risk score.
        risk_level: Overall risk level string.
        constraint_enforced: Whether a hard constraint was hit.
        validation_passed: Whether all validation checks passed.
        validation_score: Average validation score.

    Returns:
        Structured dict with OverrideDecision shape.
    """
    try:
        activity = copy.deepcopy(activity)
        action = activity.get("action_details", {})
        action_type = activity.get("action_type", "unknown")

        # --- Hard reject cases ---
        reject_reason = _check_hard_reject(
            violations, constraint_enforced, risk_score, risk_level,
        )
        if reject_reason:
            return {
                "status": "success",
                "override_needed": True,
                "action": "reject",
                "modifications": {},
                "reasoning": reject_reason,
                "suggested_fix": _suggest_fix_for_reject(
                    action, action_type, violations, policy_failures,
                ),
            }

        # --- Modification cases ---
        modifications, modify_reason = _check_modification(
            action, action_type, context, violations, policy_failures,
            risk_score, validation_score,
        )
        if modifications:
            return {
                "status": "success",
                "override_needed": True,
                "action": "modify",
                "modifications": modifications,
                "reasoning": modify_reason,
                "suggested_fix": None,
            }

        # --- No override needed ---
        return {
            "status": "success",
            "override_needed": False,
            "action": "approve",
            "modifications": {},
            "reasoning": "Activity passes all governance checks",
            "suggested_fix": None,
        }
    except Exception as exc:
        # Fail-safe: reject on error
        return {
            "status": "error",
            "override_needed": True,
            "action": "reject",
            "modifications": {},
            "reasoning": f"Override handler error (fail-safe reject): {exc}",
            "suggested_fix": "Retry with valid input data",
        }


# ---------------------------------------------------------------------------
# Hard reject logic
# ---------------------------------------------------------------------------

def _check_hard_reject(
    violations: list[dict[str, Any]],
    constraint_enforced: bool,
    risk_score: float,
    risk_level: str,
) -> str | None:
    """Check if the activity must be hard-rejected. Returns reason or None."""
    # Any hard constraint hit is an automatic reject
    if constraint_enforced:
        return "Hard constraint violated — action cannot proceed"

    # Critical violations are automatic rejects
    critical_violations = [
        v for v in violations if v.get("severity") == "critical"
    ]
    if critical_violations:
        names = [v.get("rule_name", "unknown") for v in critical_violations]
        return f"Critical rule violations: {', '.join(names)}"

    # Extreme risk is an automatic reject
    if risk_score >= _REJECT_IF_RISK_ABOVE:
        return f"Risk score {risk_score:.2f} exceeds reject threshold {_REJECT_IF_RISK_ABOVE:.2f}"

    return None


# ---------------------------------------------------------------------------
# Modification logic
# ---------------------------------------------------------------------------

def _check_modification(
    action: dict[str, Any],
    action_type: str,
    context: dict[str, Any],
    violations: list[dict[str, Any]],
    policy_failures: list[dict[str, Any]],
    risk_score: float,
    validation_score: float,
) -> tuple[dict[str, Any], str]:
    """Check if the action should be modified. Returns (modifications, reason)."""
    modifications: dict[str, Any] = {}
    reasons: list[str] = []

    # Budget reduction for medium-high risk
    budget = float(action.get("budget", 0))
    if budget > 0 and risk_score >= _MODIFY_IF_RISK_ABOVE:
        reduced = round(budget * _BUDGET_REDUCTION_FACTOR, 2)
        daily_limit = float(context.get("daily_budget_limit", 0))
        daily_used = float(context.get("daily_budget_used", 0))

        # Make sure reduced budget still fits in daily limit
        if daily_limit > 0:
            max_allowed = daily_limit - daily_used
            reduced = min(reduced, max(max_allowed, 0))

        if reduced != budget:
            modifications["budget"] = reduced
            reasons.append(
                f"Budget reduced from ${budget:.2f} to ${reduced:.2f} "
                f"due to risk score {risk_score:.2f}"
            )

    # Budget headroom warnings → suggest reduction to leave 10% headroom
    headroom_violations = [
        v for v in violations
        if v.get("rule_name") == "daily_budget_headroom"
        and v.get("severity") == "warning"
    ]
    if headroom_violations and "budget" not in modifications and budget > 0:
        daily_limit = float(context.get("daily_budget_limit", 0))
        daily_used = float(context.get("daily_budget_used", 0))
        if daily_limit > 0:
            safe_budget = max((daily_limit * 0.90) - daily_used, 0)
            safe_budget = round(min(safe_budget, budget), 2)
            if safe_budget < budget:
                modifications["budget"] = safe_budget
                reasons.append(
                    f"Budget adjusted to ${safe_budget:.2f} to maintain "
                    f"10% daily budget headroom"
                )

    # Policy failure for spending percentage → cap at 50%
    spending_failures = [
        p for p in policy_failures
        if p.get("policy_name") == "spending_policy"
    ]
    if spending_failures and "budget" not in modifications and budget > 0:
        daily_limit = float(context.get("daily_budget_limit", 0))
        if daily_limit > 0:
            capped = round(daily_limit * 0.50, 2)
            if capped < budget:
                modifications["budget"] = capped
                reasons.append(
                    f"Budget capped at ${capped:.2f} (50% of daily limit) per spending policy"
                )

    # Low validation score → add warning flag
    if validation_score < 0.50:
        modifications["governance_warning"] = True
        reasons.append(
            f"Low validation score {validation_score:.2f} — governance warning attached"
        )

    reason_str = "; ".join(reasons) if reasons else ""
    return modifications, reason_str


# ---------------------------------------------------------------------------
# Fix suggestion
# ---------------------------------------------------------------------------

def _suggest_fix_for_reject(
    action: dict[str, Any],
    action_type: str,
    violations: list[dict[str, Any]],
    policy_failures: list[dict[str, Any]],
) -> str | None:
    """Generate a suggested fix for a rejected action."""
    suggestions: list[str] = []

    for v in violations:
        if v.get("rule_name") == "max_single_action_budget":
            suggestions.append("Reduce action budget to $1000 or below")
        elif v.get("rule_name") == "daily_budget_headroom":
            suggestions.append("Reduce budget to stay within daily limit")
        elif v.get("rule_name") == "no_action_on_inactive_store":
            suggestions.append("Activate the store before performing spending actions")
        elif v.get("rule_name") == "platform_must_be_specified":
            suggestions.append("Add a 'platform' field to the action")

    for p in policy_failures:
        if p.get("policy_name") == "high_impact_approval":
            suggestions.append("Set 'explicit_approval: true' in context for high-impact actions")
        elif p.get("policy_name") == "time_restriction":
            suggestions.append("Retry outside maintenance window (06:00-24:00 UTC)")

    if not suggestions:
        return "Review and address the violations before retrying"

    return "; ".join(suggestions)
