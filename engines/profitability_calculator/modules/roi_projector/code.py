"""ROI projection engine — projects return on investment over 12 months.

Generates multi-scenario financial projections:
  - Monthly profit (conservative / expected / optimistic)
  - Cumulative ROI curve over 12 months
  - Cash flow projection (when negative, when recovery)
  - ROI percentage: (total_profit / total_investment) * 100
  - Annualized ROI for comparison with alternative investments
"""
from __future__ import annotations

from typing import Any

from .data import GROWTH_CURVE_BENCHMARKS, MONTHLY_SEASONALITY, AD_SPEND_RAMP_BY_MONTH


# Scenario multipliers relative to expected case
SCENARIO_MULTIPLIERS = {
    "conservative": 0.65,
    "expected": 1.00,
    "optimistic": 1.40,
}

# Standard projection checkpoints (days)
CHECKPOINTS = [30, 60, 90, 180, 365]


def project_roi(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Project ROI over 12 months with multiple scenarios.

    Args:
        input_payload: {
            "total_investment": float,         # All capital deployed
            "price": float,                    # Selling price per unit
            "variable_cost_per_unit": float,    # COGS + shipping + fees
            "estimated_daily_sales": float,    # Expected daily unit volume
            "monthly_fixed_costs": float,      # Shopify + apps + overhead
            "category": str,                   # For seasonality/growth curves
            "ad_spend_monthly": float,         # Monthly advertising budget
            "start_month": int,                # 1-12, month of year to start
        }

    Returns:
        Complete ROI projection with scenarios, cash flow, and milestones.
    """
    price = input_payload["price"]
    variable_cost = input_payload["variable_cost_per_unit"]
    total_investment = input_payload["total_investment"]
    base_daily_sales = input_payload.get("estimated_daily_sales", 2.0)
    monthly_fixed = input_payload.get("monthly_fixed_costs", 100.0)
    category = input_payload.get("category", "general")
    base_ad_spend = input_payload.get("ad_spend_monthly", 300.0)
    start_month = input_payload.get("start_month", 1)

    contribution_margin = price - variable_cost
    if contribution_margin <= 0:
        return {
            "status": "error",
            "error": "negative_margin",
            "message": f"Price (${price}) does not cover variable costs (${variable_cost})",
        }

    # Build 12-month projections for each scenario
    scenarios = {}
    for scenario_name, multiplier in SCENARIO_MULTIPLIERS.items():
        monthly_data = _project_monthly(
            contribution_margin=contribution_margin,
            base_daily_sales=base_daily_sales * multiplier,
            monthly_fixed=monthly_fixed,
            base_ad_spend=base_ad_spend,
            total_investment=total_investment,
            category=category,
            start_month=start_month,
        )
        scenarios[scenario_name] = monthly_data

    # Extract checkpoint snapshots (30, 60, 90, 180, 365 days)
    checkpoints = _extract_checkpoints(scenarios, total_investment)

    # Cash flow analysis from expected scenario
    cash_flow = _analyze_cash_flow(scenarios["expected"], total_investment)

    # ROI calculations
    expected_12m = scenarios["expected"]
    total_profit_12m = sum(m["net_profit"] for m in expected_12m)
    roi_pct = (total_profit_12m / total_investment) * 100 if total_investment > 0 else 0

    # Annualized ROI (for comparison with other investments)
    annualized_roi = roi_pct  # Already 12-month projection

    return {
        "status": "ok",
        "total_investment": round(total_investment, 2),
        "scenarios": {
            name: [_round_month(m) for m in months]
            for name, months in scenarios.items()
        },
        "checkpoints": checkpoints,
        "cash_flow": cash_flow,
        "roi_summary": {
            "total_profit_12m": round(total_profit_12m, 2),
            "roi_pct": round(roi_pct, 1),
            "annualized_roi_pct": round(annualized_roi, 1),
            "monthly_avg_profit": round(total_profit_12m / 12, 2),
        },
        "summary": _build_summary(roi_pct, cash_flow, total_investment, total_profit_12m),
    }


def _project_monthly(
    contribution_margin: float,
    base_daily_sales: float,
    monthly_fixed: float,
    base_ad_spend: float,
    total_investment: float,
    category: str,
    start_month: int,
) -> list[dict[str, Any]]:
    """Generate 12-month projection with growth curves and seasonality."""
    growth_curve = GROWTH_CURVE_BENCHMARKS.get(
        category, GROWTH_CURVE_BENCHMARKS["general"]
    )
    seasonality = MONTHLY_SEASONALITY
    ad_ramp = AD_SPEND_RAMP_BY_MONTH

    months = []
    cumulative_profit = 0.0
    cumulative_revenue = 0.0

    for month_idx in range(12):
        month_number = month_idx + 1

        # Growth multiplier (new stores ramp up over time)
        growth_mult = growth_curve.get(month_number, growth_curve.get(12, 1.0))

        # Seasonality adjustment (based on calendar month)
        calendar_month = ((start_month - 1 + month_idx) % 12) + 1
        season_mult = seasonality.get(calendar_month, 1.0)

        # Ad spend ramp (typically increases as you find winning ads)
        ad_mult = ad_ramp.get(month_number, ad_ramp.get(12, 1.0))
        month_ad_spend = base_ad_spend * ad_mult

        # Daily sales for this month
        daily_sales = base_daily_sales * growth_mult * season_mult
        monthly_units = daily_sales * 30

        # Revenue and costs
        gross_revenue = monthly_units * (contribution_margin + 0)  # margin already net of variable
        gross_profit = monthly_units * contribution_margin
        total_costs = monthly_fixed + month_ad_spend
        net_profit = gross_profit - total_costs

        cumulative_profit += net_profit
        cumulative_revenue += monthly_units * contribution_margin + monthly_units * 0

        months.append({
            "month": month_number,
            "calendar_month": calendar_month,
            "daily_sales": daily_sales,
            "monthly_units": monthly_units,
            "gross_profit": gross_profit,
            "ad_spend": month_ad_spend,
            "fixed_costs": monthly_fixed,
            "net_profit": net_profit,
            "cumulative_profit": cumulative_profit,
            "cumulative_roi_pct": (
                (cumulative_profit / total_investment) * 100
                if total_investment > 0 else 0
            ),
        })

    return months


def _extract_checkpoints(
    scenarios: dict[str, list[dict]], total_investment: float
) -> dict[str, Any]:
    """Extract ROI at 30, 60, 90, 180, 365-day checkpoints."""
    checkpoints = {}
    for days in CHECKPOINTS:
        month_idx = min(int(days / 30) - 1, 11)
        month_idx = max(0, month_idx)
        checkpoint = {}
        for scenario_name, months in scenarios.items():
            m = months[month_idx]
            checkpoint[scenario_name] = {
                "cumulative_profit": round(m["cumulative_profit"], 2),
                "roi_pct": round(m["cumulative_roi_pct"], 1),
                "monthly_profit": round(m["net_profit"], 2),
            }
        checkpoints[f"day_{days}"] = checkpoint
    return checkpoints


def _analyze_cash_flow(
    expected_months: list[dict], total_investment: float
) -> dict[str, Any]:
    """Determine when cash goes negative and when it recovers."""
    # Cash starts at -total_investment (you've spent the money)
    cash_position = -total_investment
    lowest_cash = cash_position
    lowest_cash_month = 0
    recovery_month = None

    monthly_cash = []
    for m in expected_months:
        cash_position += m["net_profit"]
        monthly_cash.append({
            "month": m["month"],
            "net_inflow": round(m["net_profit"], 2),
            "cash_position": round(cash_position, 2),
        })
        if cash_position < lowest_cash:
            lowest_cash = cash_position
            lowest_cash_month = m["month"]
        if recovery_month is None and cash_position >= 0:
            recovery_month = m["month"]

    return {
        "initial_outflow": round(-total_investment, 2),
        "lowest_cash_position": round(lowest_cash, 2),
        "lowest_cash_month": lowest_cash_month,
        "recovery_month": recovery_month,
        "recovered": recovery_month is not None,
        "final_cash_position": round(cash_position, 2),
        "monthly_cash_flow": monthly_cash,
    }


def _round_month(month_data: dict[str, Any]) -> dict[str, Any]:
    """Round all float values in a month record for clean output."""
    return {
        k: round(v, 2) if isinstance(v, float) else v
        for k, v in month_data.items()
    }


def _build_summary(
    roi_pct: float, cash_flow: dict, investment: float, profit: float
) -> str:
    """Human-readable ROI summary."""
    parts = []

    if roi_pct > 200:
        parts.append(f"Strong ROI: {roi_pct:.0f}% annual return on ${investment:,.0f} investment")
    elif roi_pct > 100:
        parts.append(f"Good ROI: {roi_pct:.0f}% annual return — doubles your investment")
    elif roi_pct > 50:
        parts.append(f"Moderate ROI: {roi_pct:.0f}% annual return — beats most investments")
    elif roi_pct > 0:
        parts.append(f"Low ROI: {roi_pct:.0f}% annual return — consider if worth the effort")
    else:
        parts.append(f"Negative ROI: {roi_pct:.0f}% — this product loses money over 12 months")

    if cash_flow["recovered"]:
        parts.append(f"Cash recovers in month {cash_flow['recovery_month']}")
    else:
        parts.append("Cash does NOT recover within 12 months — high risk")

    return ". ".join(parts) + "."
