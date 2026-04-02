"""Volume projection decision logic — inventory planning and viability assessment.

Takes volume projections and produces actionable decisions:
  - How much inventory to order (and when to reorder)
  - Is this product volume viable for the business model?
  - What does the growth trajectory look like month-over-month?
"""
from __future__ import annotations

from typing import Any

from .data import (
    MINIMUM_VIABLE_VOLUME,
    INVENTORY_COVERAGE_BENCHMARKS,
    get_growth_multiplier,
)


def calculate_inventory_needs(projections: dict[str, Any]) -> dict[str, Any]:
    """Calculate how much inventory to order based on volume projections.

    Uses the expected scenario + 30% safety buffer.
    Inventory must cover 2 months of projected demand.

    Args:
        projections: {
            "expected_monthly_volume": float,
            "category": str,
            "lead_time_days": int | None,   # Supplier lead time (default 30)
            "price": float,                 # For investment calculation
            "cost_per_unit": float | None,  # COGS per unit
        }
    """
    monthly_volume = projections.get("expected_monthly_volume", 0)
    category = projections.get("category", "general")
    lead_time_days = projections.get("lead_time_days", 30)
    price = projections.get("price", 0)
    cost_per_unit = projections.get("cost_per_unit", price * 0.35)

    benchmarks = INVENTORY_COVERAGE_BENCHMARKS.get(
        category, INVENTORY_COVERAGE_BENCHMARKS["general"]
    )
    coverage_months = benchmarks["coverage_months"]
    buffer_pct = benchmarks["buffer_pct"]
    reorder_pct = benchmarks["reorder_threshold_pct"]

    # Base inventory: coverage_months worth of expected volume
    base_inventory = monthly_volume * coverage_months

    # Add safety buffer
    safety_buffer = base_inventory * buffer_pct
    total_order = round(base_inventory + safety_buffer)

    # Reorder point: when stock hits this level, place next order
    reorder_point = round(total_order * reorder_pct)

    # Lead time coverage: can we survive a restock cycle?
    daily_volume = monthly_volume / 30
    lead_time_units = round(daily_volume * lead_time_days)
    lead_time_covered = reorder_point >= lead_time_units

    # Investment required
    inventory_investment = round(total_order * cost_per_unit, 2)

    return {
        "recommended_order_quantity": total_order,
        "safety_buffer_units": round(safety_buffer),
        "reorder_point_units": reorder_point,
        "reorder_point_pct": reorder_pct,
        "lead_time_coverage": {
            "lead_time_days": lead_time_days,
            "units_needed_during_lead_time": lead_time_units,
            "covered_by_reorder_point": lead_time_covered,
        },
        "inventory_investment": inventory_investment,
        "coverage_months": coverage_months,
        "days_of_stock": round(total_order / max(daily_volume, 0.1)),
        "summary": _inventory_summary(total_order, inventory_investment, coverage_months),
    }


def assess_volume_viability(projected_monthly: dict[str, Any]) -> dict[str, Any]:
    """Assess whether projected volume is enough to be worth selling.

    Checks against minimum viable thresholds by category.

    Args:
        projected_monthly: {
            "expected_monthly_units": float,
            "pessimistic_monthly_units": float,
            "price": float,
            "category": str,
            "margin_pct": float | None,   # Gross margin (0-1)
        }
    """
    expected = projected_monthly.get("expected_monthly_units", 0)
    pessimistic = projected_monthly.get("pessimistic_monthly_units", 0)
    price = projected_monthly.get("price", 0)
    category = projected_monthly.get("category", "general")
    margin_pct = projected_monthly.get("margin_pct", 0.40)

    thresholds = MINIMUM_VIABLE_VOLUME.get(category, MINIMUM_VIABLE_VOLUME["general"])
    min_units = thresholds["min_monthly_units"]
    good_units = thresholds["good_monthly_units"]

    expected_revenue = expected * price
    expected_gross_profit = expected_revenue * margin_pct
    pessimistic_revenue = pessimistic * price

    # Viability scoring
    score = 0
    reasons = []
    warnings = []

    if expected >= good_units:
        score += 50
        reasons.append(f"Strong volume: {expected:.0f} units/month exceeds good threshold ({good_units})")
    elif expected >= min_units:
        score += 30
        reasons.append(f"Viable volume: {expected:.0f} units/month meets minimum ({min_units})")
    else:
        score += 10
        warnings.append(f"Low volume: {expected:.0f} units/month below minimum viable ({min_units})")

    if pessimistic >= min_units:
        score += 30
        reasons.append("Even pessimistic scenario meets minimum volume")
    else:
        score += 10
        warnings.append(f"Pessimistic scenario ({pessimistic:.0f}/mo) below minimum viable")

    if expected_gross_profit >= 2000:
        score += 20
        reasons.append(f"Gross profit ${expected_gross_profit:,.0f}/month — covers operating costs")
    elif expected_gross_profit >= 500:
        score += 10
        reasons.append(f"Gross profit ${expected_gross_profit:,.0f}/month — tight but possible")
    else:
        warnings.append(f"Gross profit ${expected_gross_profit:,.0f}/month — may not cover costs")

    verdict = _viability_verdict(score)

    return {
        "viable": score >= 50,
        "score": min(100, score),
        "verdict": verdict,
        "expected_monthly_units": expected,
        "expected_monthly_revenue": round(expected_revenue, 2),
        "expected_monthly_gross_profit": round(expected_gross_profit, 2),
        "pessimistic_monthly_revenue": round(pessimistic_revenue, 2),
        "thresholds": thresholds,
        "reasons": reasons,
        "warnings": warnings,
    }


def model_growth_trajectory(
    months: int = 12,
    starting_velocity: float = 0.0,
    steady_state_volume: float = 100.0,
    category: str = "general",
) -> list[dict[str, Any]]:
    """Model month-by-month growth trajectory for a new product.

    Args:
        months: How many months to project
        starting_velocity: Current monthly sales (0 for new product)
        steady_state_volume: Expected volume once fully ramped
        category: For ramp curve lookup
    """
    trajectory = []
    for month in range(1, months + 1):
        ramp_multiplier = get_growth_multiplier(category, month)
        projected = starting_velocity + (steady_state_volume * ramp_multiplier)

        mom_growth = None
        if len(trajectory) > 0 and trajectory[-1]["projected_units"] > 0:
            prev = trajectory[-1]["projected_units"]
            mom_growth = round(((projected - prev) / prev) * 100, 1)

        trajectory.append({
            "month": month,
            "ramp_multiplier": ramp_multiplier,
            "projected_units": round(projected, 1),
            "projected_pct_of_steady_state": round(ramp_multiplier * 100, 1),
            "month_over_month_growth_pct": mom_growth,
        })

    return trajectory


def _inventory_summary(order_qty: int, investment: float, coverage: float) -> str:
    """Human-readable inventory recommendation."""
    if order_qty <= 0:
        return "No inventory needed — projected volume is zero"
    return (
        f"Order {order_qty} units (${investment:,.0f} investment) for "
        f"{coverage} months of coverage. Reorder when 60% depleted."
    )


def _viability_verdict(score: int) -> str:
    """Determine viability verdict from score."""
    if score >= 80:
        return "highly_viable"
    if score >= 50:
        return "viable"
    if score >= 30:
        return "marginal"
    return "not_viable"
