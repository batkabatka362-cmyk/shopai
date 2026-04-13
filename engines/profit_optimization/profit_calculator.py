"""Profit Optimization Engine — profit calculator.

Computes real financial metrics: gross revenue, COGS, gross profit,
ad spend, net profit, margins, per-unit economics, and break-even.

All math is real — no faking, no random numbers.
"""
from __future__ import annotations

import copy
import math
from typing import Any


def calculate_profit(aggregated: dict[str, Any]) -> dict[str, Any]:
    """Calculate full profit breakdown from aggregated data.

    Args:
        aggregated: Output from data_aggregator.aggregate_data().

    Returns:
        Structured dict with ProfitMetrics.
    """
    try:
        data = copy.deepcopy(aggregated)

        sales = data.get("sales", {})
        ads = data.get("ads", {})
        costs = data.get("costs", {})

        # --- Revenue ---
        gross_revenue = float(sales.get("total_revenue", 0.0))
        units_sold = int(sales.get("units_sold", 0))
        orders = int(sales.get("orders", 0))
        refunds = int(sales.get("refunds", 0))
        aov = float(sales.get("avg_order_value", 0.0))

        # Estimate refund loss: refunds * average order value
        refund_loss = refunds * aov if aov > 0 else 0.0
        net_revenue = gross_revenue - refund_loss

        # --- Costs ---
        cogs = float(costs.get("cogs", 0.0))
        shipping = float(costs.get("shipping", 0.0))
        platform_fees = float(costs.get("platform_fees", 0.0))
        tools = float(costs.get("tools", 0.0))
        labor = float(costs.get("labor", 0.0))
        ad_spend = float(ads.get("total_spend", 0.0))

        # --- Profit calculations ---
        gross_profit = net_revenue - cogs
        gross_margin = gross_profit / net_revenue if net_revenue > 0 else 0.0

        total_operating_costs = shipping + platform_fees + tools + labor
        total_cost = cogs + ad_spend + total_operating_costs
        net_profit = net_revenue - total_cost

        net_margin = net_profit / net_revenue if net_revenue > 0 else 0.0

        # --- Per-unit economics ---
        revenue_per_unit = net_revenue / units_sold if units_sold > 0 else 0.0
        cost_per_unit = total_cost / units_sold if units_sold > 0 else 0.0
        profit_per_unit = net_profit / units_sold if units_sold > 0 else 0.0

        # --- Break-even ---
        # Fixed costs = tools + labor (don't scale with units)
        # Variable cost per unit = (cogs + shipping + platform_fees + ad_spend) / units_sold
        fixed_costs = tools + labor
        variable_total = cogs + shipping + platform_fees + ad_spend
        variable_per_unit = variable_total / units_sold if units_sold > 0 else 0.0

        if revenue_per_unit > variable_per_unit:
            contribution_margin = revenue_per_unit - variable_per_unit
            break_even_units = math.ceil(fixed_costs / contribution_margin)
            break_even_revenue = break_even_units * revenue_per_unit
        else:
            # Cannot break even if variable costs exceed revenue per unit
            break_even_units = 0
            break_even_revenue = 0.0

        metrics: dict[str, Any] = {
            "gross_revenue": round(gross_revenue, 2),
            "refund_loss": round(refund_loss, 2),
            "net_revenue": round(net_revenue, 2),
            "cogs": round(cogs, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_margin": round(gross_margin, 4),
            "ad_spend": round(ad_spend, 2),
            "shipping": round(shipping, 2),
            "platform_fees": round(platform_fees, 2),
            "tools": round(tools, 2),
            "labor": round(labor, 2),
            "total_operating_costs": round(total_operating_costs, 2),
            "total_cost": round(total_cost, 2),
            "net_profit": round(net_profit, 2),
            "net_margin": round(net_margin, 4),
            "revenue_per_unit": round(revenue_per_unit, 2),
            "cost_per_unit": round(cost_per_unit, 2),
            "profit_per_unit": round(profit_per_unit, 2),
            "break_even_units": break_even_units,
            "break_even_revenue": round(break_even_revenue, 2),
        }

        return {
            "status": "success",
            "metrics": metrics,
        }
    except Exception as exc:
        return {
            "status": "error",
            "metrics": {},
            "error": f"Profit calculation failed: {exc}",
        }
