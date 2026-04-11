"""Loyalty Engine — reward recommender.

Recommends rewards based on customer behavior, tier, and points
balance. Matches reward value to customer engagement level.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Default reward catalog by tier
# ---------------------------------------------------------------------------

_DEFAULT_REWARDS: dict[str, list[dict[str, Any]]] = {
    "bronze": [
        {"reward": "5% off next order", "points_cost": 500, "type": "discount"},
        {"reward": "Free shipping on next order", "points_cost": 300, "type": "shipping"},
    ],
    "silver": [
        {"reward": "10% off next order", "points_cost": 800, "type": "discount"},
        {"reward": "Free shipping for 30 days", "points_cost": 600, "type": "shipping"},
        {"reward": "Early access to new products", "points_cost": 400, "type": "access"},
    ],
    "gold": [
        {"reward": "15% off next order", "points_cost": 1000, "type": "discount"},
        {"reward": "Free shipping for 90 days", "points_cost": 1200, "type": "shipping"},
        {"reward": "Exclusive product bundle", "points_cost": 2000, "type": "product"},
        {"reward": "$25 store credit", "points_cost": 2500, "type": "credit"},
    ],
    "platinum": [
        {"reward": "20% off next order", "points_cost": 1500, "type": "discount"},
        {"reward": "Free shipping for 1 year", "points_cost": 3000, "type": "shipping"},
        {"reward": "Premium product bundle", "points_cost": 4000, "type": "product"},
        {"reward": "$50 store credit", "points_cost": 5000, "type": "credit"},
        {"reward": "VIP event invitation", "points_cost": 6000, "type": "experience"},
    ],
}


def recommend_rewards(
    tier_statuses: list[dict[str, Any]],
    reward_catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recommend rewards for each customer based on tier and points.

    Args:
        tier_statuses: List of CustomerTierStatus dicts from tier_manager.
        reward_catalog: Optional custom reward catalog. Falls back to defaults.

    Returns:
        Structured dict with per-customer reward recommendations.
    """
    try:
        items = copy.deepcopy(tier_statuses)
        recommendations: list[dict[str, Any]] = []

        for status in items:
            cid = str(status.get("customer_id", "unknown"))
            tier = str(status.get("current_tier", "bronze"))
            points = int(status.get("points", 0))

            # Get available rewards for this tier
            if reward_catalog:
                available = [r for r in reward_catalog if int(r.get("points_cost", 0)) <= points]
            else:
                tier_rewards = _DEFAULT_REWARDS.get(tier, _DEFAULT_REWARDS["bronze"])
                available = [r for r in tier_rewards if int(r.get("points_cost", 0)) <= points]

            # Sort by points cost descending (best value first)
            available = sorted(available, key=lambda r: int(r.get("points_cost", 0)), reverse=True)

            # Recommend top 3
            recommended = available[:3]

            # Build reason
            if recommended:
                reason = f"{tier.capitalize()} member with {points} points — {len(recommended)} rewards available"
            else:
                reason = f"{tier.capitalize()} member with {points} points — earn more to unlock rewards"

            recommendations.append({
                "customer_id": cid,
                "recommended_rewards": recommended,
                "reason": reason,
            })

        return {
            "status": "success",
            "recommendations": recommendations,
        }
    except Exception as exc:
        return {
            "status": "error",
            "recommendations": [],
            "error": f"Reward recommendation failed: {exc}",
        }
