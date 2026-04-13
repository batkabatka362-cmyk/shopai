"""Action Planner — creates a specific, time-bound action plan after selection.

Generates a week-by-week plan: Week 1 (order samples), Week 2 (create listing),
Week 3 (launch ads), etc. Each step has concrete dates, budget allocation,
and success criteria. Plans are customized by product type.

Returns the engine contract: {status, data, meta, error}.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from .data import PLAN_TEMPLATES, BUDGET_ALLOCATIONS, MILESTONE_DEFINITIONS
from .logic import customize_plan_for_product, estimate_plan_budget, set_milestones
from .rules import validate_action_plan


def create_action_plan(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Create a concrete, actionable launch plan for the selected product.

    Args:
        input_payload: dict with keys:
            - selected_product (dict): the chosen product
            - investment (float): estimated total investment
            - product_type (str): category/type of product
            - goal (str): profit|growth|balanced
            - start_date (str): optional ISO date for plan start

    Returns:
        Engine contract dict {status, data, meta, error}.
    """
    try:
        selected = input_payload.get("selected_product")
        if not selected or not isinstance(selected, dict):
            return _error("selected_product is required")

        investment = input_payload.get("investment", 5000.0)
        product_type = input_payload.get("product_type", "general")
        goal = input_payload.get("goal", "balanced")
        start_date_str = input_payload.get("start_date")

        # --- Determine start date ---
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            except ValueError:
                start_date = datetime.now()
        else:
            start_date = datetime.now()

        # --- Get base plan template ---
        base_plan = _get_base_plan(product_type)

        # --- Customize plan for the specific product ---
        customized = customize_plan_for_product(base_plan, product_type, selected)

        # --- Assign dates to each step ---
        dated_plan = _assign_dates(customized, start_date)

        # --- Estimate budget per step ---
        budgeted = estimate_plan_budget(dated_plan, investment)

        # --- Set milestones with success criteria ---
        with_milestones = set_milestones(budgeted, goal)

        # --- Calculate total budget and timeline ---
        total_budget = sum(s.get("budget", 0) for s in with_milestones)
        total_weeks = max(s.get("week", 1) for s in with_milestones) if with_milestones else 0
        end_date = start_date + timedelta(weeks=total_weeks)

        # --- Validate plan ---
        validation = validate_action_plan(with_milestones, investment)

        product_name = selected.get("product_name", selected.get("product_id", "Unknown"))

        return {
            "status": "success",
            "data": {
                "plan_name": f"Launch Plan: {product_name}",
                "steps": with_milestones,
                "timeline": {
                    "start_date": start_date.strftime("%Y-%m-%d"),
                    "end_date": end_date.strftime("%Y-%m-%d"),
                    "total_weeks": total_weeks,
                },
                "budget": {
                    "total_investment": investment,
                    "allocated": round(total_budget, 2),
                    "unallocated": round(investment - total_budget, 2),
                },
                "milestones": [
                    s for s in with_milestones if s.get("is_milestone")
                ],
                "validation": validation,
            },
            "meta": {
                "module": "action_planner",
                "product_type": product_type,
                "steps_count": len(with_milestones),
                "goal": goal,
            },
            "error": None,
        }

    except Exception as exc:
        return _error(f"Action plan creation failed: {exc}")


def _get_base_plan(product_type: str) -> list[dict[str, Any]]:
    """Get the base plan template for the product type."""
    template = PLAN_TEMPLATES.get(product_type, PLAN_TEMPLATES["general"])
    # Deep copy to avoid mutating the template
    import copy
    return copy.deepcopy(template)


def _assign_dates(
    steps: list[dict[str, Any]], start_date: datetime,
) -> list[dict[str, Any]]:
    """Assign concrete dates to each step based on the start date."""
    for step in steps:
        week = step.get("week", 1)
        step_start = start_date + timedelta(weeks=week - 1)
        step_end = step_start + timedelta(days=6)
        step["start_date"] = step_start.strftime("%Y-%m-%d")
        step["end_date"] = step_end.strftime("%Y-%m-%d")
        step["deadline"] = step_end.strftime("%Y-%m-%d")
    return steps


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {"module": "action_planner"},
        "error": message,
    }
