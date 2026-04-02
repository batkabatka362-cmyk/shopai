"""Action Planner — core logic for plan customization, budgeting, and milestones.

Customizes generic plans for specific product types, allocates budget
across steps, and defines measurable milestones with success criteria.
"""

from __future__ import annotations

from typing import Any

from .data import BUDGET_ALLOCATIONS, MILESTONE_DEFINITIONS


def customize_plan_for_product(
    base_plan: list[dict[str, Any]],
    product_type: str,
    product: dict[str, Any],
) -> list[dict[str, Any]]:
    """Customize the base action plan for the specific product.

    Adjusts step priorities, adds product-specific notes, and removes
    steps that do not apply to the product type.

    Args:
        base_plan: The template plan steps.
        product_type: The product category (electronics, apparel, etc.).
        product: The selected product dict with scores and data.

    Returns:
        Customized list of plan steps.
    """
    risk_data = product.get("risk", {}) or {}
    risk_level = risk_data.get("risk_level", "moderate")
    margin = (product.get("profitability") or {}).get("margin", 0)
    demand_score = (product.get("demand") or {}).get("demand_score", 50)

    customized: list[dict[str, Any]] = []

    for step in base_plan:
        step = dict(step)  # Shallow copy

        # Adjust for risk level
        if risk_level in ("high", "critical") and step.get("phase") == "launch":
            step["notes"] = step.get("notes", "") + (
                " Given the elevated risk, start with a smaller test batch."
            )
            step["priority"] = "high"

        # Adjust for low demand
        if demand_score < 40 and step.get("action_type") == "marketing":
            step["notes"] = step.get("notes", "") + (
                " Demand is low — allocate extra budget to demand generation."
            )
            step["budget_modifier"] = 1.3

        # Adjust for thin margins
        if margin < 15 and step.get("action_type") == "inventory":
            step["notes"] = step.get("notes", "") + (
                " Thin margins — order conservatively and negotiate shipping costs."
            )
            step["budget_modifier"] = 0.7

        # Product type specific adjustments
        if product_type == "electronics" and step.get("action_type") == "quality":
            step["notes"] = step.get("notes", "") + (
                " Electronics require extra quality testing — check certifications."
            )

        if product_type == "apparel" and step.get("action_type") == "listing":
            step["notes"] = step.get("notes", "") + (
                " Apparel listings need size charts and multiple color/angle photos."
            )

        customized.append(step)

    return customized


def estimate_plan_budget(
    steps: list[dict[str, Any]], total_investment: float,
) -> list[dict[str, Any]]:
    """Allocate budget to each step based on standard allocation ratios.

    Uses BUDGET_ALLOCATIONS to assign a percentage of the total investment
    to each action type. Applies budget_modifier if set during customization.

    Args:
        steps: Plan steps with action_type and optional budget_modifier.
        total_investment: Total available investment.

    Returns:
        Steps with budget amounts assigned.
    """
    for step in steps:
        action_type = step.get("action_type", "other")
        allocation = BUDGET_ALLOCATIONS.get(action_type, BUDGET_ALLOCATIONS["other"])
        base_pct = allocation["percentage"]
        modifier = step.get("budget_modifier", 1.0)

        budget = round(total_investment * (base_pct / 100) * modifier, 2)
        step["budget"] = budget
        step["budget_note"] = (
            f"{base_pct}% of ${total_investment:,.0f}"
            + (f" (adjusted x{modifier})" if modifier != 1.0 else "")
        )

    return steps


def set_milestones(
    steps: list[dict[str, Any]], goal: str,
) -> list[dict[str, Any]]:
    """Set milestones with success criteria on key steps.

    Marks certain steps as milestones — checkpoints where the seller
    should evaluate progress before continuing. Each milestone has
    specific, measurable success criteria.

    Args:
        steps: Plan steps with dates and budgets.
        goal: The optimization goal (profit|growth|balanced).

    Returns:
        Steps with milestone markers and success criteria added.
    """
    milestone_phases = {"sample_validation", "launch", "review"}

    for step in steps:
        phase = step.get("phase", "")
        action_type = step.get("action_type", "")

        # Check if this step is a milestone
        is_milestone = phase in milestone_phases or step.get("is_milestone", False)
        step["is_milestone"] = is_milestone

        if is_milestone:
            # Get milestone definition from reference data
            milestone_def = MILESTONE_DEFINITIONS.get(
                phase, MILESTONE_DEFINITIONS.get("default"),
            )
            if milestone_def:
                step["success_criteria"] = milestone_def["success_criteria"]
                step["decision_point"] = milestone_def["decision_point"]
                step["failure_action"] = milestone_def["failure_action"]

            # Adjust success criteria based on goal
            if goal == "profit" and "margin" not in str(step.get("success_criteria", "")):
                step.setdefault("goal_criteria", "Margin must meet or exceed projections")
            elif goal == "growth" and "volume" not in str(step.get("success_criteria", "")):
                step.setdefault("goal_criteria", "Sales volume must show growth trajectory")

    return steps


def calculate_critical_path(
    steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Identify steps on the critical path that cannot be delayed.

    Args:
        steps: Plan steps with dependencies and dates.

    Returns:
        List of critical path steps.
    """
    critical = []
    for step in steps:
        if step.get("priority") == "high" or step.get("is_milestone"):
            critical.append({
                "step": step.get("title", ""),
                "week": step.get("week", 0),
                "deadline": step.get("deadline", ""),
                "reason": "Milestone" if step.get("is_milestone") else "High priority",
            })
    return critical
