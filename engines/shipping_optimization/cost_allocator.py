"""Shipping Optimization Engine — cost allocator.

Allocates shipping cost across four strategies:
  1. Absorb (free shipping) — merchant pays 100%
  2. Pass-through — customer pays 100%
  3. Partial subsidy — merchant absorbs a fixed portion
  4. Built-into-price — shipping cost baked into product prices

For each strategy, computes margin impact and effective cost to both
merchant and customer.

No LLM calls — pure financial modelling.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Strategy definitions
# ---------------------------------------------------------------------------

_STRATEGIES: dict[str, dict[str, Any]] = {
    "free_shipping": {
        "label": "Free Shipping (Absorb)",
        "merchant_pct": 1.0,
        "customer_pct": 0.0,
        "built_in_pct": 0.0,
    },
    "pass_through": {
        "label": "Customer Pays (Pass-Through)",
        "merchant_pct": 0.0,
        "customer_pct": 1.0,
        "built_in_pct": 0.0,
    },
    "partial_subsidy": {
        "label": "Partial Subsidy",
        "merchant_pct": 0.50,
        "customer_pct": 0.50,
        "built_in_pct": 0.0,
    },
    "built_into_price": {
        "label": "Built Into Price",
        "merchant_pct": 0.0,
        "customer_pct": 0.0,
        "built_in_pct": 1.0,
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def allocate_costs(
    avg_shipping_cost: float,
    avg_order_value: float,
    avg_margin_pct: float = 0.40,
    monthly_orders: int = 500,
    subsidy_pct: float = 0.50,
) -> dict[str, Any]:
    """Compute cost allocation for each shipping strategy.

    For every strategy, calculates:
      - How much the merchant absorbs per order
      - How much the customer pays per order
      - How much is built into product prices
      - Total monthly shipping cost
      - Effective margin impact

    Args:
        avg_shipping_cost: Average shipping cost per order (USD).
        avg_order_value: Current average order value (USD).
        avg_margin_pct: Average gross margin as a decimal.
        monthly_orders: Monthly order volume.
        subsidy_pct: Merchant's share under partial-subsidy strategy.

    Returns:
        Structured dict with CostAllocation list.
    """
    try:
        ship = max(0.01, float(avg_shipping_cost))
        aov = max(1.0, float(avg_order_value))
        margin = max(0.05, min(0.95, float(avg_margin_pct)))
        orders = max(1, int(monthly_orders))
        subsidy = max(0.0, min(1.0, float(subsidy_pct)))

        gross_profit_per_order = aov * margin
        monthly_ship_total = ship * orders

        # Override partial subsidy split with the supplied ratio
        strategies = {
            "free_shipping": {"merchant_pct": 1.0, "customer_pct": 0.0, "built_in_pct": 0.0},
            "pass_through": {"merchant_pct": 0.0, "customer_pct": 1.0, "built_in_pct": 0.0},
            "partial_subsidy": {"merchant_pct": subsidy, "customer_pct": 1.0 - subsidy, "built_in_pct": 0.0},
            "built_into_price": {"merchant_pct": 0.0, "customer_pct": 0.0, "built_in_pct": 1.0},
        }

        allocations: list[dict[str, Any]] = []

        for strat_id, split in strategies.items():
            merchant_absorbs = ship * split["merchant_pct"]
            customer_pays = ship * split["customer_pct"]
            built_in = ship * split["built_in_pct"]

            # Margin impact: what the merchant effectively loses per order
            # Built-into-price: margin is preserved because price is raised,
            # but apparent price is higher (potential conversion impact).
            if strat_id == "built_into_price":
                # Margin preserved, but we note the price increase
                margin_impact_per_order = 0.0
                effective_price_increase = built_in
            else:
                margin_impact_per_order = -merchant_absorbs
                effective_price_increase = 0.0

            effective_margin = margin + (margin_impact_per_order / aov) if aov > 0 else margin

            allocations.append({
                "strategy": strat_id,
                "label": _STRATEGIES.get(strat_id, {}).get("label", strat_id),
                "merchant_absorbs": round(merchant_absorbs, 2),
                "customer_pays": round(customer_pays, 2),
                "built_into_price": round(built_in, 2),
                "total_shipping_cost": round(ship, 2),
                "monthly_merchant_cost": round(merchant_absorbs * orders, 2),
                "monthly_customer_cost": round(customer_pays * orders, 2),
                "effective_margin_impact": round(effective_margin - margin, 4),
                "effective_margin_pct": round(effective_margin, 4),
                "effective_price_increase": round(effective_price_increase, 2),
            })

        # Rank by merchant cost (ascending)
        allocations.sort(key=lambda a: a["merchant_absorbs"])

        return {
            "status": "success",
            "allocations": allocations,
            "count": len(allocations),
            "context": {
                "avg_shipping_cost": round(ship, 2),
                "avg_order_value": round(aov, 2),
                "avg_margin_pct": round(margin, 4),
                "gross_profit_per_order": round(gross_profit_per_order, 2),
                "monthly_orders": orders,
                "total_monthly_shipping": round(monthly_ship_total, 2),
                "shipping_as_pct_of_revenue": round(ship / aov, 4) if aov > 0 else 0.0,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "allocations": [],
            "count": 0,
            "context": {},
            "error": f"Cost allocation failed: {exc}",
        }
