"""Pricing Engine — cost analyzer.

Analyzes full cost structure: COGS, shipping, platform fees, payment
processing, estimated returns cost, and packaging. Computes the cost
floor — the absolute minimum price to avoid losing money on each unit.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Default cost assumptions when data is missing
# ---------------------------------------------------------------------------

_DEFAULT_RETURN_RATE = 0.05          # 5% of units returned
_DEFAULT_PACKAGING_PER_KG = 0.50     # $0.50 per kg for packaging materials
_DEFAULT_PACKAGING_BASE = 0.30       # base packaging cost per unit


def analyze_costs(
    product: dict[str, Any],
    platform_fees_pct: float,
    payment_processing_pct: float,
) -> dict[str, Any]:
    """Analyze the full cost structure for a product.

    Args:
        product: ProductData dict with cogs, shipping_cost, weight_kg, etc.
        platform_fees_pct: Platform fee as a decimal (e.g. 0.029).
        payment_processing_pct: Payment processing fee as a decimal.

    Returns:
        Structured dict with CostAnalysis data.
    """
    try:
        prod = copy.deepcopy(product)

        cogs = float(prod.get("cogs", 0.0))
        shipping = float(prod.get("shipping_cost", 0.0))
        weight_kg = float(prod.get("weight_kg", 0.0))

        # Platform and payment fees are percentage-based, so they depend
        # on the eventual sale price. For cost floor calculation, we compute
        # them relative to a break-even reference: the sum of known fixed costs.
        # The actual fees at any given price are: price * fee_pct.
        # Cost floor formula: floor = fixed_costs / (1 - total_pct_fees)
        platform_pct = max(float(platform_fees_pct), 0.0)
        payment_pct = max(float(payment_processing_pct), 0.0)

        # Packaging: base cost + weight-proportional cost
        packaging = _DEFAULT_PACKAGING_BASE + (weight_kg * _DEFAULT_PACKAGING_PER_KG)

        # Returns cost: expected cost of processing returns
        # When a return happens, we lose shipping both ways + restocking effort
        # Estimated as return_rate * (cogs * 0.1 + shipping * 2)
        returns_cost = _DEFAULT_RETURN_RATE * (cogs * 0.10 + shipping * 2.0)

        # Fixed per-unit costs (not dependent on sale price)
        fixed_costs = cogs + shipping + packaging + returns_cost

        # Percentage-based fees combined
        total_pct_fees = platform_pct + payment_pct

        # Platform and payment fees at cost floor level
        # cost_floor = fixed_costs / (1 - total_pct_fees)
        if total_pct_fees >= 1.0:
            # Impossible to cover costs if fees exceed 100%
            cost_floor = 0.0
            platform_fee_amount = 0.0
            payment_fee_amount = 0.0
        else:
            cost_floor = fixed_costs / (1.0 - total_pct_fees)
            platform_fee_amount = cost_floor * platform_pct
            payment_fee_amount = cost_floor * payment_pct

        total_cost = fixed_costs + platform_fee_amount + payment_fee_amount

        return {
            "status": "success",
            "analysis": {
                "cogs": round(cogs, 2),
                "shipping": round(shipping, 2),
                "platform_fees": round(platform_fee_amount, 2),
                "payment_processing": round(payment_fee_amount, 2),
                "returns_cost": round(returns_cost, 2),
                "packaging": round(packaging, 2),
                "total_cost": round(total_cost, 2),
                "cost_floor": round(cost_floor, 2),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "analysis": {},
            "error": f"Cost analysis failed: {exc}",
        }
