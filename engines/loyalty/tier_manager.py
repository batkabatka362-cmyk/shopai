"""Loyalty Engine — tier manager.

Manages customer tiers (bronze/silver/gold/platinum) based on
points balance. Calculates tier status, progress to next tier,
and tier distribution.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def manage_tiers(
    points_calculations: list[dict[str, Any]],
    tiers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Determine tier status for each customer.

    Args:
        points_calculations: List of CustomerPoints dicts from points_calculator.
        tiers: List of TierDefinition dicts from program_designer.

    Returns:
        Structured dict with per-customer tier status.
    """
    try:
        items = copy.deepcopy(points_calculations)
        sorted_tiers = sorted(
            copy.deepcopy(tiers),
            key=lambda t: int(t.get("min_points", 0)),
        )

        statuses: list[dict[str, Any]] = []
        tier_counts: dict[str, int] = {}

        for calc in items:
            cid = str(calc.get("customer_id", "unknown"))
            points = int(calc.get("points_balance", 0))

            # Determine current tier
            current_tier = sorted_tiers[0]["name"] if sorted_tiers else "bronze"
            current_idx = 0
            for idx, tier in enumerate(sorted_tiers):
                if points >= int(tier.get("min_points", 0)):
                    current_tier = tier["name"]
                    current_idx = idx

            # Determine next tier and progress
            if current_idx < len(sorted_tiers) - 1:
                next_tier_def = sorted_tiers[current_idx + 1]
                next_tier = next_tier_def["name"]
                next_min = int(next_tier_def.get("min_points", 0))
                current_min = int(sorted_tiers[current_idx].get("min_points", 0))
                tier_range = next_min - current_min
                if tier_range > 0:
                    progress = round((points - current_min) / tier_range, 2)
                    progress = min(max(progress, 0.0), 1.0)
                else:
                    progress = 1.0
                points_to_next = max(0, next_min - points)
            else:
                next_tier = "max"
                progress = 1.0
                points_to_next = 0

            tier_counts[current_tier] = tier_counts.get(current_tier, 0) + 1

            statuses.append({
                "customer_id": cid,
                "current_tier": current_tier,
                "points": points,
                "next_tier": next_tier,
                "next_tier_progress": progress,
                "points_to_next_tier": points_to_next,
            })

        return {
            "status": "success",
            "statuses": statuses,
            "tier_distribution": tier_counts,
        }
    except Exception as exc:
        return {
            "status": "error",
            "statuses": [],
            "error": f"Tier management failed: {exc}",
        }
