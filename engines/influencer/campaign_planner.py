"""Influencer Engine — campaign planner.

Plans influencer campaigns with budget allocation, content types,
and estimated ROI based on scored influencers.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Campaign type defaults
# ---------------------------------------------------------------------------

_CAMPAIGN_DEFAULTS: dict[str, dict[str, Any]] = {
    "sponsored_post": {"duration_days": 30, "content_types": ["feed_post", "story"], "conversion_rate": 0.02},
    "product_review": {"duration_days": 45, "content_types": ["video_review", "blog_post"], "conversion_rate": 0.035},
    "brand_ambassador": {"duration_days": 90, "content_types": ["feed_post", "story", "video", "live"], "conversion_rate": 0.025},
    "giveaway": {"duration_days": 14, "content_types": ["feed_post", "story"], "conversion_rate": 0.05},
}


def plan_campaign(
    scored_influencers: list[dict[str, Any]],
    budget: float,
    campaign_type: str,
    category: str,
) -> dict[str, Any]:
    """Plan an influencer campaign with budget allocation and ROI estimate.

    Args:
        scored_influencers: List of ScoredInfluencer dicts, sorted by score.
        budget: Total campaign budget.
        campaign_type: Type of campaign.
        category: Product/brand category.

    Returns:
        Structured dict with campaign plan and estimated ROI.
    """
    try:
        influencers = copy.deepcopy(scored_influencers)
        defaults = _CAMPAIGN_DEFAULTS.get(
            campaign_type,
            _CAMPAIGN_DEFAULTS["sponsored_post"],
        )

        duration_days = defaults["duration_days"]
        content_types = defaults["content_types"]
        base_conversion_rate = defaults["conversion_rate"]

        # Select influencers that fit within budget
        selected: list[dict[str, Any]] = []
        remaining_budget = budget
        total_reach = 0
        total_cost = 0.0

        for inf in influencers:
            cost = float(inf.get("estimated_cost", 0.0))
            if cost <= remaining_budget:
                allocation = {
                    "influencer_id": inf["id"],
                    "influencer_name": inf["name"],
                    "allocated_budget": cost,
                    "content_deliverables": content_types,
                }
                selected.append(allocation)
                remaining_budget -= cost
                total_cost += cost
                total_reach += int(inf.get("followers", 0))

        # Estimate conversions
        # Reach is discounted by avg engagement rate
        avg_engagement = 0.0
        if influencers:
            avg_engagement = sum(
                float(i.get("engagement_rate", 0.0)) for i in influencers
            ) / len(influencers)

        effective_reach = int(total_reach * (avg_engagement / 100.0))
        estimated_conversions = int(effective_reach * base_conversion_rate)

        # ROI estimate: assume $50 avg order value
        estimated_revenue = estimated_conversions * 50.0
        estimated_roi = (
            round((estimated_revenue - total_cost) / total_cost, 2)
            if total_cost > 0 else 0.0
        )

        campaign_plan: dict[str, Any] = {
            "campaign_name": f"{category.title()} {campaign_type.replace('_', ' ').title()}",
            "duration_days": duration_days,
            "total_budget": round(total_cost, 2),
            "influencer_allocations": selected,
            "content_types": content_types,
            "estimated_reach": total_reach,
            "estimated_conversions": estimated_conversions,
        }

        return {
            "status": "success",
            "campaign_plan": campaign_plan,
            "estimated_roi": estimated_roi,
        }
    except Exception as exc:
        return {
            "status": "error",
            "campaign_plan": {},
            "estimated_roi": 0.0,
            "error": f"Campaign planning failed: {exc}",
        }
