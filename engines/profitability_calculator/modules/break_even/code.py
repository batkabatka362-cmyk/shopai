"""Break-even calculation engine — how many units to sell to recover investment.

Core formula:
    break_even_units = fixed_costs / (price - variable_cost_per_unit)
    break_even_revenue = break_even_units * price
    break_even_timeline = break_even_units / estimated_daily_sales

Fixed costs include:
    - Initial inventory investment (first batch)
    - Marketing launch budget (ads, influencers, promos)
    - Setup costs (product photography, listing creation, branding)
    - Samples cost (pre-launch samples for review/testing)
"""
from __future__ import annotations

from typing import Any

from .data import (
    LAUNCH_COSTS_BY_PRODUCT_TYPE,
    DAILY_SALES_VELOCITY_BY_CATEGORY,
    SETUP_COST_BENCHMARKS,
)


def calculate_break_even(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Calculate break-even point for a product launch.

    Args:
        input_payload: {
            "price": float,                        # Selling price per unit
            "variable_cost_per_unit": float,        # COGS + shipping + fees per unit
            "fixed_costs": {                        # Optional — auto-estimated if missing
                "inventory_investment": float,
                "marketing_launch_budget": float,
                "setup_costs": float,               # Photography, listing, branding
                "samples_cost": float,
            },
            "estimated_daily_sales": float | None,  # Optional — looked up from category
            "category": str,                        # For benchmarks
            "product_type": str,                    # For launch cost estimates
            "first_batch_units": int | None,        # Size of first inventory order
        }

    Returns:
        Complete break-even analysis with sensitivity scenarios.
    """
    price = input_payload["price"]
    variable_cost = input_payload["variable_cost_per_unit"]
    category = input_payload.get("category", "general")
    product_type = input_payload.get("product_type", "general")

    # Resolve fixed costs — use provided values or estimate from benchmarks
    fixed_costs = _resolve_fixed_costs(input_payload, product_type)
    total_fixed_costs = sum(fixed_costs.values())

    # Contribution margin per unit (what each sale contributes toward fixed costs)
    contribution_margin = price - variable_cost
    if contribution_margin <= 0:
        return _negative_margin_result(price, variable_cost, fixed_costs)

    # Core break-even calculation
    break_even_units = total_fixed_costs / contribution_margin
    break_even_revenue = break_even_units * price

    # Timeline estimation
    daily_sales = _resolve_daily_sales(input_payload, category)
    break_even_days = break_even_units / max(daily_sales, 0.1)

    # First batch coverage check
    first_batch = input_payload.get("first_batch_units") or int(break_even_units * 1.2)
    batch_covers_break_even = first_batch >= break_even_units

    # Sensitivity analysis
    sensitivity = _run_sensitivity_analysis(
        total_fixed_costs, price, variable_cost, daily_sales
    )

    return {
        "status": "ok",
        "break_even": {
            "units": round(break_even_units, 1),
            "revenue": round(break_even_revenue, 2),
            "days": round(break_even_days, 1),
            "months": round(break_even_days / 30, 1),
        },
        "contribution_margin": {
            "per_unit": round(contribution_margin, 2),
            "margin_pct": round((contribution_margin / price) * 100, 1),
        },
        "fixed_costs": fixed_costs,
        "total_fixed_costs": round(total_fixed_costs, 2),
        "daily_sales_estimate": daily_sales,
        "first_batch": {
            "units": first_batch,
            "covers_break_even": batch_covers_break_even,
            "surplus_units": max(0, first_batch - int(break_even_units)),
        },
        "sensitivity": sensitivity,
        "summary": _build_summary(break_even_units, break_even_days, contribution_margin),
    }


def _resolve_fixed_costs(payload: dict[str, Any], product_type: str) -> dict[str, float]:
    """Resolve fixed costs from payload or estimate from benchmarks."""
    provided = payload.get("fixed_costs", {})
    benchmarks = LAUNCH_COSTS_BY_PRODUCT_TYPE.get(
        product_type, LAUNCH_COSTS_BY_PRODUCT_TYPE["general"]
    )
    return {
        "inventory_investment": provided.get(
            "inventory_investment", benchmarks["inventory_investment"]
        ),
        "marketing_launch_budget": provided.get(
            "marketing_launch_budget", benchmarks["marketing_launch_budget"]
        ),
        "setup_costs": provided.get("setup_costs", benchmarks["setup_costs"]),
        "samples_cost": provided.get("samples_cost", benchmarks["samples_cost"]),
    }


def _resolve_daily_sales(payload: dict[str, Any], category: str) -> float:
    """Resolve daily sales estimate from payload or category benchmarks."""
    if payload.get("estimated_daily_sales"):
        return payload["estimated_daily_sales"]
    velocity = DAILY_SALES_VELOCITY_BY_CATEGORY.get(category, {"new_listing": 1.5})
    return velocity["new_listing"]


def _negative_margin_result(
    price: float, variable_cost: float, fixed_costs: dict[str, float]
) -> dict[str, Any]:
    """Return result when contribution margin is zero or negative."""
    return {
        "status": "error",
        "error": "negative_contribution_margin",
        "message": (
            f"Price (${price:.2f}) does not cover variable costs "
            f"(${variable_cost:.2f}). Break-even is impossible at this price."
        ),
        "fixed_costs": fixed_costs,
        "recommendation": "Increase price or reduce variable costs before proceeding.",
    }


def _run_sensitivity_analysis(
    total_fixed: float, price: float, variable_cost: float, daily_sales: float
) -> dict[str, Any]:
    """What-if scenarios: price drops 10%, volume drops 50%."""
    scenarios = {}

    # Scenario 1: Price is 10% lower
    lower_price = price * 0.90
    lower_margin = lower_price - variable_cost
    if lower_margin > 0:
        be_units = total_fixed / lower_margin
        scenarios["price_10pct_lower"] = {
            "price": round(lower_price, 2),
            "break_even_units": round(be_units, 1),
            "break_even_days": round(be_units / max(daily_sales, 0.1), 1),
            "impact": f"+{round(((be_units / (total_fixed / (price - variable_cost))) - 1) * 100, 1)}% more units needed",
        }
    else:
        scenarios["price_10pct_lower"] = {
            "price": round(lower_price, 2),
            "break_even_units": None,
            "message": "Margin goes negative — break-even impossible",
        }

    # Scenario 2: Volume is 50% lower
    half_sales = daily_sales * 0.50
    base_be_units = total_fixed / (price - variable_cost)
    scenarios["volume_50pct_lower"] = {
        "daily_sales": round(half_sales, 2),
        "break_even_units": round(base_be_units, 1),
        "break_even_days": round(base_be_units / max(half_sales, 0.1), 1),
        "impact": "Same units needed, but 2x longer timeline",
    }

    # Scenario 3: Both price -10% AND volume -50% (worst case)
    if lower_margin > 0:
        worst_units = total_fixed / lower_margin
        scenarios["worst_case"] = {
            "description": "Price -10% AND volume -50%",
            "break_even_units": round(worst_units, 1),
            "break_even_days": round(worst_units / max(half_sales, 0.1), 1),
        }

    return scenarios


def _build_summary(be_units: float, be_days: float, margin: float) -> str:
    """Human-readable break-even summary."""
    if be_days <= 30:
        timeline = f"Excellent — break-even in ~{int(be_days)} days (within first month)"
    elif be_days <= 60:
        timeline = f"Good — break-even in ~{int(be_days)} days (within two months)"
    elif be_days <= 90:
        timeline = f"Acceptable — break-even in ~{int(be_days)} days (within first quarter)"
    elif be_days <= 180:
        timeline = f"Slow — break-even in ~{int(be_days)} days. Consider reducing launch costs"
    else:
        timeline = f"Warning — break-even in ~{int(be_days)} days (>{int(be_days/30)} months). Risky launch"

    return (
        f"Need to sell {int(be_units)} units to break even. "
        f"${margin:.2f} contribution per unit. {timeline}."
    )
