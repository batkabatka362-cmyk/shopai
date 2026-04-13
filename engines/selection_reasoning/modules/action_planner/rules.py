"""Action Planner — constraint rules for actionable, time-bound plans.

Ensures every plan has concrete dates, budget per step, and measurable
success criteria at each milestone. A plan without these elements
is a wish, not a plan.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Action plan rule definitions
# ---------------------------------------------------------------------------
ACTION_PLAN_RULES: dict[str, dict[str, Any]] = {
    "must_have_dates": {
        "description": "Every step must have a concrete start and end date",
        "severity": "critical",
        "action": "Assign dates based on start date and week number",
    },
    "must_have_budget": {
        "description": "Every step must specify its budget allocation",
        "severity": "critical",
        "action": "Calculate budget from total investment and allocation percentages",
    },
    "must_have_success_criteria": {
        "description": "Every milestone must define measurable success criteria",
        "severity": "critical",
        "action": "Add specific, measurable criteria: 'X units sold' or 'Y% margin achieved'",
    },
    "budget_must_not_exceed_investment": {
        "description": "Total step budgets must not exceed the total investment",
        "severity": "critical",
        "action": "Reduce step budgets proportionally to fit within investment",
    },
    "minimum_steps": {
        "description": "Plan must have at least 4 actionable steps",
        "threshold": 4,
        "severity": "warning",
        "action": "A meaningful launch plan needs at least preparation, listing, launch, and review steps",
    },
    "first_step_within_7_days": {
        "description": "First action step should start within 7 days",
        "max_delay_days": 7,
        "severity": "warning",
        "action": "Move the first step earlier — momentum matters in product launches",
    },
    "must_include_review_step": {
        "description": "Plan must include a review/evaluation step",
        "severity": "warning",
        "action": "Add a review milestone at week 4 or 6 to evaluate performance",
    },
}


def validate_action_plan(
    steps: list[dict[str, Any]], investment: float,
) -> dict[str, Any]:
    """Validate an action plan against all plan rules.

    Args:
        steps: List of plan step dicts.
        investment: Total investment amount.

    Returns:
        Dict with valid flag, violations, warnings, and passed rules.
    """
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    passed: list[str] = []

    # --- Must have dates ---
    rule = ACTION_PLAN_RULES["must_have_dates"]
    no_dates = [s for s in steps if not s.get("start_date") or not s.get("end_date")]
    if no_dates:
        violations.append({
            "rule": "must_have_dates",
            "severity": rule["severity"],
            "detail": f"{len(no_dates)} step(s) missing dates",
            "action": rule["action"],
        })
    else:
        passed.append("must_have_dates")

    # --- Must have budget ---
    rule = ACTION_PLAN_RULES["must_have_budget"]
    no_budget = [s for s in steps if s.get("budget") is None]
    if no_budget:
        violations.append({
            "rule": "must_have_budget",
            "severity": rule["severity"],
            "detail": f"{len(no_budget)} step(s) missing budget",
            "action": rule["action"],
        })
    else:
        passed.append("must_have_budget")

    # --- Must have success criteria on milestones ---
    rule = ACTION_PLAN_RULES["must_have_success_criteria"]
    milestones = [s for s in steps if s.get("is_milestone")]
    no_criteria = [m for m in milestones if not m.get("success_criteria")]
    if no_criteria:
        violations.append({
            "rule": "must_have_success_criteria",
            "severity": rule["severity"],
            "detail": f"{len(no_criteria)} milestone(s) missing success criteria",
            "action": rule["action"],
        })
    else:
        passed.append("must_have_success_criteria")

    # --- Budget must not exceed investment ---
    rule = ACTION_PLAN_RULES["budget_must_not_exceed_investment"]
    total_budget = sum(s.get("budget", 0) for s in steps)
    if total_budget > investment * 1.05:  # 5% tolerance
        violations.append({
            "rule": "budget_must_not_exceed_investment",
            "severity": rule["severity"],
            "detail": f"Total budget ${total_budget:,.0f} exceeds investment ${investment:,.0f}",
            "action": rule["action"],
        })
    else:
        passed.append("budget_must_not_exceed_investment")

    # --- Minimum steps ---
    rule = ACTION_PLAN_RULES["minimum_steps"]
    if len(steps) < rule["threshold"]:
        warnings.append({
            "rule": "minimum_steps",
            "severity": rule["severity"],
            "detail": f"Plan has {len(steps)} steps (min {rule['threshold']})",
            "action": rule["action"],
        })
    else:
        passed.append("minimum_steps")

    # --- Must include review step ---
    rule = ACTION_PLAN_RULES["must_include_review_step"]
    has_review = any(s.get("phase") == "review" for s in steps)
    if not has_review:
        warnings.append({
            "rule": "must_include_review_step",
            "severity": rule["severity"],
            "action": rule["action"],
        })
    else:
        passed.append("must_include_review_step")

    return {
        "valid": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "passed_rules": passed,
        "total_steps": len(steps),
        "total_milestones": len(milestones),
        "total_budget": round(total_budget, 2),
    }
