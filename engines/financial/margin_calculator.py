"""Financial Engine — margin calculator.

Calculates margins: gross margin, net margin, contribution margin,
and per-product margin analysis.
"""
from __future__ import annotations

import copy
from typing import Any


def calculate_margins(
    revenue: dict[str, Any],
    costs: dict[str, Any],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate margin metrics.

    Args:
        revenue: Revenue breakdown from revenue_calculator.
        costs: Cost breakdown from cost_analyzer.
        products: Product records with price/cost info.

    Returns:
        Structured dict with margin analysis.
    """
    try:
        total_revenue = float(revenue.get("total_revenue", 0))
        total_cogs = float(costs.get("total_cogs", 0))
        total_costs = float(costs.get("total_costs", 0))

        gross_margin = total_revenue - total_cogs
        gross_margin_pct = (
            round(gross_margin / total_revenue * 100, 2) if total_revenue > 0 else 0.0
        )

        net_income = total_revenue - total_costs
        net_margin_pct = (
            round(net_income / total_revenue * 100, 2) if total_revenue > 0 else 0.0
        )

        # Per-product margins
        prod_data = copy.deepcopy(products)
        margin_by_product: list[dict[str, Any]] = []

        rev_per_product = revenue.get("revenue_per_product", {})

        for prod in prod_data:
            pid = str(prod.get("id", ""))
            price = float(prod.get("price", 0))
            cost = float(prod.get("cost", prod.get("unit_cost", 0)))
            prod_rev = rev_per_product.get(pid, 0.0)

            if price > 0:
                prod_margin = round((price - cost) / price * 100, 2)
            else:
                prod_margin = 0.0

            margin_by_product.append({
                "product_id": pid,
                "price": price,
                "cost": cost,
                "margin_pct": prod_margin,
                "revenue": prod_rev,
            })

        margin_by_product.sort(key=lambda m: m["margin_pct"], reverse=True)

        contribution_margin = round(gross_margin - float(costs.get("total_operating", 0)), 2)

        return {
            "status": "success",
            "margins": {
                "gross_margin_pct": gross_margin_pct,
                "net_margin_pct": net_margin_pct,
                "contribution_margin": contribution_margin,
                "margin_by_product": margin_by_product,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "margins": {},
            "error": f"Margin calculation failed: {exc}",
        }
