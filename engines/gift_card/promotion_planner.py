"""Gift Card Engine — promotion planner.

Plans gift card promotions: bonus value campaigns,
seasonal offers, bulk corporate deals.
"""
from __future__ import annotations

import copy
from typing import Any


def plan_promotions(
    program_health: dict[str, Any],
    program_config: dict[str, Any],
) -> dict[str, Any]:
    """Plan gift card promotions.

    Args:
        program_health: Current program health metrics.
        program_config: Program configuration.

    Returns:
        Structured dict with promotion plans.
    """
    try:
        health = copy.deepcopy(program_health)
        config = copy.deepcopy(program_config)
        promotions: list[dict[str, Any]] = []

        utilization = float(health.get("utilization_rate_pct", 0))
        active_count = int(health.get("active_cards_count", 0))
        total_issued = int(health.get("total_issued", 0))

        # Low utilization: bonus value promo
        if utilization < 50:
            promotions.append({
                "type": "bonus_value",
                "description": "Buy $50 gift card, get $10 bonus — boost utilization",
                "target": "new_buyers",
                "expected_uplift_pct": 15.0,
                "cost_estimate": round(active_count * 10 * 0.3, 2),
            })

        # Seasonal promotions
        promotions.append({
            "type": "seasonal",
            "description": "Holiday gift card bundle: 3-pack at 10% discount",
            "target": "holiday_shoppers",
            "expected_uplift_pct": 25.0,
            "cost_estimate": 0.0,
        })

        # Corporate/bulk deals
        if total_issued > 100:
            promotions.append({
                "type": "corporate_bulk",
                "description": "Corporate bulk purchase: 15% discount on 50+ cards",
                "target": "corporate_buyers",
                "expected_uplift_pct": 20.0,
                "cost_estimate": 0.0,
            })

        # Re-engagement for dormant cards
        dormant = int(health.get("active_cards_count", 0))
        if dormant > 0:
            promotions.append({
                "type": "reengagement",
                "description": f"Reminder campaign for {dormant} active cards with balance",
                "target": "dormant_holders",
                "expected_uplift_pct": 10.0,
                "cost_estimate": round(dormant * 0.50, 2),
            })

        return {
            "status": "success",
            "promotions": promotions,
            "total_promotions": len(promotions),
        }
    except Exception as exc:
        return {
            "status": "error",
            "promotions": [],
            "error": f"Promotion planning failed: {exc}",
        }
