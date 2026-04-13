"""Returns Management Engine — cost calculator.

Calculates return costs including refunds, shipping, and restocking fees.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Cost defaults
# ---------------------------------------------------------------------------

_DEFAULT_SHIPPING_COST = 8.50
_DEFAULT_PROCESSING_COST = 2.00


def calculate_costs(
    processed: list[dict[str, Any]],
    return_policy: dict[str, Any],
) -> dict[str, Any]:
    """Calculate total costs for all processed returns.

    Args:
        processed: List of ProcessedReturn dicts from return_processor.
        return_policy: ReturnPolicy dict with rules.

    Returns:
        Structured dict with cost breakdown.
    """
    try:
        processed = copy.deepcopy(processed)
        policy = copy.deepcopy(return_policy)

        free_shipping = bool(policy.get("free_return_shipping", False))
        restocking_fee_pct = float(policy.get("restocking_fee_pct", 0.0))

        total_refunds = 0.0
        shipping_costs = 0.0
        restocking_costs = 0.0
        eligible_count = 0

        for proc in processed:
            if not proc.get("eligible", False):
                continue

            eligible_count += 1
            refund = float(proc.get("refund_amount", 0.0))
            total_refunds += refund

            # Shipping cost (merchant pays if free returns)
            if free_shipping:
                shipping_costs += _DEFAULT_SHIPPING_COST

            # Restocking cost (processing labor per return)
            restocking_costs += _DEFAULT_PROCESSING_COST

            # If restocking fee is applied, it offsets merchant cost
            if restocking_fee_pct > 0:
                # The fee was already deducted from refund in processor;
                # here we track the original item value for cost analysis
                original_value = refund / (1.0 - restocking_fee_pct / 100.0)
                fee_collected = original_value - refund
                restocking_costs -= fee_collected  # offset

        total_cost = total_refunds + shipping_costs + max(restocking_costs, 0.0)
        avg_cost = round(total_cost / eligible_count, 2) if eligible_count > 0 else 0.0

        cost_breakdown: dict[str, Any] = {
            "total_refunds": round(total_refunds, 2),
            "shipping_costs": round(shipping_costs, 2),
            "restocking_costs": round(max(restocking_costs, 0.0), 2),
            "total_cost": round(total_cost, 2),
            "avg_cost_per_return": avg_cost,
        }

        return {
            "status": "success",
            "cost_breakdown": cost_breakdown,
        }
    except Exception as exc:
        return {
            "status": "error",
            "cost_breakdown": {},
            "error": f"Cost calculation failed: {exc}",
        }
