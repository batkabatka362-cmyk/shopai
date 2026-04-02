"""Decision functions for financial risk management.

Provides max loss calculations, cash flow risk assessment, and capital
allocation recommendations for e-commerce product investments.
"""

from __future__ import annotations

from typing import Any

from .data import (
    get_loss_probability,
    get_margin_erosion,
    CASH_FLOW_BENCHMARKS,
)


def calculate_max_loss(
    investment: float, scenarios: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Calculate the maximum potential loss across different scenarios.

    Args:
        investment: total capital invested in USD.
        scenarios: optional dict with keys:
            - product_type (str): for loss probability lookup
            - monthly_fixed_costs (float): ongoing costs if product fails
            - months_to_liquidate (int): time to sell off remaining inventory
            - liquidation_recovery (float): % of COGS recovered (default 0.30)
            - ad_spend_sunk (float): non-recoverable ad spend (default 0)

    Returns:
        Engine contract with max loss analysis.
    """
    if investment <= 0:
        return _error("Investment must be positive")

    if scenarios is None:
        scenarios = {}

    product_type = scenarios.get("product_type", "evergreen")
    fixed_costs = scenarios.get("monthly_fixed_costs", 500.0)
    months_liquidate = scenarios.get("months_to_liquidate", 3)
    recovery_rate = scenarios.get("liquidation_recovery", 0.30)
    ad_sunk = scenarios.get("ad_spend_sunk", 0.0)

    loss_probs = get_loss_probability(product_type)

    # --- Worst case: total loss ---
    liquidation_recovery = round(investment * recovery_rate, 2)
    burn_during_liquidation = round(fixed_costs * months_liquidate, 2)
    worst_case_loss = round(
        investment - liquidation_recovery + burn_during_liquidation + ad_sunk, 2
    )

    # --- Partial loss scenario ---
    partial_recovery = round(investment * 0.60, 2)  # Recover 60% through discounted sales
    partial_loss = round(investment - partial_recovery + ad_sunk, 2)

    # --- Break even scenario ---
    break_even_cost = round(ad_sunk + (fixed_costs * 2), 2)  # Only lose sunk costs

    # --- Expected value calculation ---
    expected_loss = round(
        (loss_probs["total_loss_prob"] * worst_case_loss)
        + (loss_probs["partial_loss_prob"] * partial_loss)
        + (loss_probs["break_even_prob"] * break_even_cost)
        + (loss_probs["profit_prob"] * 0),  # No loss in profit scenario
        2,
    )

    # Risk-adjusted return
    can_afford = worst_case_loss < investment * 1.5

    return {
        "status": "success",
        "data": {
            "scenarios": {
                "worst_case": {
                    "total_loss": worst_case_loss,
                    "probability": loss_probs["total_loss_prob"],
                    "breakdown": {
                        "investment_lost": investment,
                        "liquidation_recovery": -liquidation_recovery,
                        "burn_during_liquidation": burn_during_liquidation,
                        "sunk_ad_spend": ad_sunk,
                    },
                },
                "partial_loss": {
                    "total_loss": partial_loss,
                    "probability": loss_probs["partial_loss_prob"],
                },
                "break_even": {
                    "total_loss": break_even_cost,
                    "probability": loss_probs["break_even_prob"],
                },
                "profitable": {
                    "total_loss": 0,
                    "probability": loss_probs["profit_prob"],
                },
            },
            "expected_loss": expected_loss,
            "worst_case_loss": worst_case_loss,
            "can_afford_worst_case": can_afford,
            "recommendation": (
                "Investment is within acceptable risk tolerance"
                if can_afford
                else "WARNING: worst-case loss exceeds 1.5x investment — reduce exposure"
            ),
        },
        "meta": {"product_type": product_type, "investment": investment},
        "error": None,
    }


def assess_cash_flow_risk(projections: dict[str, Any]) -> dict[str, Any]:
    """Assess cash flow risk based on revenue and cost projections.

    Args:
        projections: dict with keys:
            - monthly_revenue (float): expected monthly revenue
            - cogs_percent (float): COGS as fraction of revenue
            - monthly_fixed_costs (float): fixed operating costs
            - initial_investment (float): upfront capital deployed
            - ramp_up_months (int): months to reach full revenue (default 2)
            - payment_delay_days (int): days until payment received (default 14)

    Returns:
        Engine contract with cash flow risk analysis.
    """
    monthly_rev = projections.get("monthly_revenue", 0)
    cogs_pct = projections.get("cogs_percent", 0.35)
    fixed_costs = projections.get("monthly_fixed_costs", 500)
    investment = projections.get("initial_investment", 5000)
    ramp_months = projections.get("ramp_up_months", 2)
    payment_delay = projections.get("payment_delay_days", 14)

    if monthly_rev <= 0:
        return _error("monthly_revenue must be positive")

    # Project cash flow month by month
    cumulative = -investment
    monthly_flows: list[dict[str, Any]] = []
    month_positive = None

    for month in range(1, 13):
        # Revenue ramps up linearly during ramp period
        ramp_factor = min(month / max(ramp_months, 1), 1.0)
        rev = round(monthly_rev * ramp_factor, 2)
        cogs = round(rev * cogs_pct, 2)
        gross_profit = round(rev - cogs, 2)
        net = round(gross_profit - fixed_costs, 2)
        cumulative = round(cumulative + net, 2)

        monthly_flows.append({
            "month": month,
            "revenue": rev,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "fixed_costs": fixed_costs,
            "net_cash_flow": net,
            "cumulative": cumulative,
        })

        if cumulative >= 0 and month_positive is None:
            month_positive = month

    # Cash flow gap: max negative cumulative
    max_negative = min(f["cumulative"] for f in monthly_flows)
    working_capital_needed = round(abs(min(max_negative, 0)) + (fixed_costs * 1.5), 2)

    # Payment delay impact
    daily_revenue = monthly_rev / 30
    cash_tied_in_transit = round(daily_revenue * payment_delay, 2)

    risk_level = "low"
    if month_positive is None:
        risk_level = "critical"
    elif month_positive > 6:
        risk_level = "high"
    elif month_positive > 4:
        risk_level = "moderate"

    return {
        "status": "success",
        "data": {
            "months_to_positive_cash_flow": month_positive,
            "risk_level": risk_level,
            "monthly_projections": monthly_flows,
            "max_cash_deficit": max_negative,
            "working_capital_needed": working_capital_needed,
            "cash_tied_in_transit": cash_tied_in_transit,
            "end_of_year_cumulative": monthly_flows[-1]["cumulative"],
            "recommendation": (
                f"Ensure ${working_capital_needed:,.0f} in reserves to survive "
                f"until month {month_positive or 'N/A'} break-even"
            ),
        },
        "meta": {
            "projection_months": 12,
            "ramp_up_months": ramp_months,
            "payment_delay_days": payment_delay,
        },
        "error": None,
    }


def recommend_capital_allocation(
    budget: float, risk_level: str
) -> dict[str, Any]:
    """Recommend how to allocate capital across products by risk level.

    Core principle: never bet more than X% of budget on a single product.

    Args:
        budget: total available capital in USD.
        risk_level: low|moderate|high|critical.

    Returns:
        Engine contract with allocation recommendations.
    """
    if budget <= 0:
        return _error("Budget must be positive")

    # Max allocation per product by risk level
    max_pct_map = {
        "low": 0.40,
        "moderate": 0.30,
        "high": 0.20,
        "critical": 0.10,
    }
    max_pct = max_pct_map.get(risk_level, 0.30)
    max_per_product = round(budget * max_pct, 2)

    # Reserve requirements
    reserve_pct = 0.25  # Always keep 25% in reserve (3-month operating buffer)
    reserve = round(budget * reserve_pct, 2)
    deployable = round(budget - reserve, 2)

    # Recommended number of products to diversify
    ideal_products = max(round(deployable / max_per_product), 2)

    # Allocation tiers
    allocation = {
        "inventory_investment": round(deployable * 0.50, 2),
        "marketing_budget": round(deployable * 0.25, 2),
        "operating_reserve": reserve,
        "contingency_fund": round(deployable * 0.10, 2),
        "testing_budget": round(deployable * 0.15, 2),
    }

    return {
        "status": "success",
        "data": {
            "total_budget": budget,
            "deployable_capital": deployable,
            "operating_reserve": reserve,
            "max_per_product": max_per_product,
            "max_percent_per_product": max_pct,
            "recommended_product_count": ideal_products,
            "allocation": allocation,
            "rules_applied": [
                f"Max {int(max_pct * 100)}% of budget on single product ({risk_level} risk)",
                "Maintain 25% operating reserve (3-month buffer)",
                "Allocate 15% for product testing before full commitment",
                "Keep 10% contingency for unexpected costs",
            ],
            "recommendation": (
                f"With ${budget:,.0f} budget at {risk_level} risk, invest max "
                f"${max_per_product:,.0f} per product across {ideal_products} products. "
                f"Keep ${reserve:,.0f} in reserve."
            ),
        },
        "meta": {"risk_level": risk_level, "budget": budget},
        "error": None,
    }


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {},
        "error": message,
    }
