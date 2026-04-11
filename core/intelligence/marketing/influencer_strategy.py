"""Influencer marketing strategy — micro-influencers deliver 5x better ROI."""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_float

INFLUENCER_TIERS = {
    "nano": {"followers": (1000, 10000), "engagement_rate": 0.07, "cost_per_post": (50, 250), "roi_multiplier": 5.0},
    "micro": {"followers": (10000, 50000), "engagement_rate": 0.04, "cost_per_post": (250, 1000), "roi_multiplier": 4.0},
    "mid": {"followers": (50000, 500000), "engagement_rate": 0.02, "cost_per_post": (1000, 5000), "roi_multiplier": 2.0},
    "macro": {"followers": (500000, 1000000), "engagement_rate": 0.015, "cost_per_post": (5000, 15000), "roi_multiplier": 1.2},
    "mega": {"followers": (1000000, float("inf")), "engagement_rate": 0.01, "cost_per_post": (15000, 100000), "roi_multiplier": 0.8},
}


def plan_influencer_strategy(products: list[dict[str, Any]]) -> dict[str, Any]:
    """Plan influencer marketing strategy — micro-influencers deliver 5x better ROI."""
    avg_price = 0
    if products:
        prices = [safe_float(p.get("price", 0)) for p in products if isinstance(p, dict)]
        avg_price = sum(prices) / max(len(prices), 1)

    # Recommend tier based on product price
    if avg_price < 30:
        recommended = "nano"
    elif avg_price < 100:
        recommended = "micro"
    elif avg_price < 500:
        recommended = "mid"
    else:
        recommended = "macro"

    tier = INFLUENCER_TIERS[recommended]
    budget_range = tier["cost_per_post"]

    return {
        "recommended_tier": recommended,
        "tier_details": {
            k: {
                "followers": f"{v['followers'][0]:,}-{v['followers'][1]:,}" if v["followers"][1] != float("inf") else f"{v['followers'][0]:,}+",
                "avg_engagement": f"{v['engagement_rate']*100:.1f}%",
                "cost_per_post": f"${v['cost_per_post'][0]}-${v['cost_per_post'][1]}",
                "roi_multiplier": f"{v['roi_multiplier']}x",
            }
            for k, v in INFLUENCER_TIERS.items()
        },
        "budget_recommendation": {
            "per_post": f"${budget_range[0]}-${budget_range[1]}",
            "monthly_budget": f"${budget_range[0]*4}-${budget_range[1]*4}",
            "posts_per_month": "4-8 posts across 3-5 influencers",
        },
        "key_insight": "Micro-influencers (10K-50K followers) deliver 5x better ROI than mega-influencers. "
                      "Their audiences trust recommendations more and engagement rates are 4x higher.",
    }
