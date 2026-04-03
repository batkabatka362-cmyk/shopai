"""Monetization Engine — revenue scanner.

Scans product and customer data for revenue opportunities:
cross-sell potential, bundling options, price optimization.
"""
from __future__ import annotations

import copy
from typing import Any


def scan_revenue(
    products: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    revenue_data: dict[str, Any],
) -> dict[str, Any]:
    """Scan for revenue opportunities.

    Args:
        products: Product catalog.
        customers: Customer records.
        revenue_data: Current revenue metrics.

    Returns:
        Structured dict with identified opportunities.
    """
    try:
        prods = copy.deepcopy(products)
        custs = copy.deepcopy(customers)

        opportunities: list[dict[str, Any]] = []
        total_revenue = float(revenue_data.get("total_revenue", 0))

        # Cross-sell: customers buying from single category
        single_cat_customers = 0
        for cust in custs:
            categories = cust.get("categories_purchased", [])
            if len(categories) == 1:
                single_cat_customers += 1

        if single_cat_customers > 0 and custs:
            cross_sell_pct = single_cat_customers / len(custs)
            if cross_sell_pct > 0.3:
                opportunities.append({
                    "type": "cross_sell",
                    "potential_revenue": round(total_revenue * 0.05 * cross_sell_pct, 2),
                    "effort": "low",
                    "description": f"{round(cross_sell_pct*100)}% of customers buy from single category",
                })

        # Bundle opportunities: frequently co-purchased products
        co_purchase_count = int(revenue_data.get("co_purchase_pairs", 0))
        if co_purchase_count > 5:
            opportunities.append({
                "type": "bundling",
                "potential_revenue": round(total_revenue * 0.03, 2),
                "effort": "medium",
                "description": f"{co_purchase_count} product pairs frequently bought together",
            })

        # Price optimization: products with high demand but low margins
        for prod in prods:
            price = float(prod.get("price", 0))
            cost = float(prod.get("cost", prod.get("unit_cost", 0)))
            demand = float(prod.get("quantity_sold", prod.get("demand", 0)))

            if price > 0 and cost > 0:
                margin = (price - cost) / price
                if margin < 0.2 and demand > 50:
                    opportunities.append({
                        "type": "price_optimization",
                        "potential_revenue": round(demand * price * 0.05, 2),
                        "effort": "low",
                        "description": f"Product '{prod.get('title', prod.get('id', ''))}' has thin margin ({round(margin*100)}%) with high demand",
                    })

        return {
            "status": "success",
            "opportunities": opportunities,
            "total_found": len(opportunities),
        }
    except Exception as exc:
        return {
            "status": "error",
            "opportunities": [],
            "error": f"Revenue scanning failed: {exc}",
        }
