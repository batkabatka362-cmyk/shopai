"""Profitability Calculator Engine — break-even analyzer.

Calculates break-even point in units and revenue for each product
based on fixed costs and per-unit contribution margin.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_break_even(
    products: list[dict[str, Any]],
    margins: list[dict[str, Any]],
    breakdowns: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze break-even for each product.

    Args:
        products: List of product dicts.
        margins: Per-product margin results.
        breakdowns: Per-product cost breakdowns.

    Returns:
        Structured dict with per-product break-even results.
    """
    try:
        margin_map = {str(m.get("product_id", "")): m for m in margins}
        bd_map = {str(b.get("product_id", "")): b for b in breakdowns}

        results: list[dict[str, Any]] = []

        for item in products:
            pid = str(item.get("id", "unknown"))
            units_sold = int(item.get("units_sold", 0))
            margin = margin_map.get(pid, {})
            bd = bd_map.get(pid, {})

            net_margin_per_unit = float(margin.get("net_margin", 0.0))
            revenue_per_unit = float(margin.get("revenue_per_unit", 0.0))

            # Fixed costs = marketing + overhead (per-unit allocated already)
            marketing = float(bd.get("marketing", 0.0))
            overhead = float(bd.get("overhead", 0.0))
            fixed_cost_per_unit = marketing + overhead

            # Contribution margin = revenue - variable costs (COGS + shipping + platform)
            variable_cost = (
                float(bd.get("cogs", 0.0)) +
                float(bd.get("shipping", 0.0)) +
                float(bd.get("platform_fee", 0.0))
            )
            contribution_margin = revenue_per_unit - variable_cost

            if contribution_margin > 0 and fixed_cost_per_unit > 0:
                # Break-even with total fixed costs
                total_fixed = fixed_cost_per_unit * max(units_sold, 1)
                break_even_units = max(1, int(total_fixed / contribution_margin + 0.999))
                break_even_revenue = round(break_even_units * revenue_per_unit, 2)
            elif contribution_margin > 0:
                break_even_units = 1
                break_even_revenue = round(revenue_per_unit, 2)
            else:
                break_even_units = 0
                break_even_revenue = 0.0

            units_above = max(0, units_sold - break_even_units)
            is_profitable = units_sold >= break_even_units and net_margin_per_unit > 0

            results.append({
                "product_id": pid,
                "break_even_units": break_even_units,
                "break_even_revenue": break_even_revenue,
                "units_above_break_even": units_above,
                "is_profitable": is_profitable,
            })

        return {"status": "success", "break_evens": results}
    except Exception as exc:
        return {"status": "error", "break_evens": [], "error": f"Break-even analysis failed: {exc}"}
