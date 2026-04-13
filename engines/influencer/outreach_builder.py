"""Influencer Engine — outreach builder.

Builds personalized outreach messages for influencer partnerships.
Generates templates based on influencer profile and campaign context.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def build_outreach(
    scored_influencers: list[dict[str, Any]],
    campaign_plan: dict[str, Any],
    category: str,
) -> dict[str, Any]:
    """Build outreach message templates for selected influencers.

    Args:
        scored_influencers: List of ScoredInfluencer dicts.
        campaign_plan: CampaignPlan dict from campaign_planner.
        category: Product/brand category.

    Returns:
        Structured dict with outreach templates.
    """
    try:
        influencers = copy.deepcopy(scored_influencers)
        plan = copy.deepcopy(campaign_plan)

        campaign_name = str(plan.get("campaign_name", "Partnership"))
        content_types = plan.get("content_types", ["sponsored content"])
        allocated_ids = {
            str(a.get("influencer_id", ""))
            for a in plan.get("influencer_allocations", [])
        }

        templates: list[dict[str, Any]] = []

        for inf in influencers:
            inf_id = str(inf.get("id", ""))
            if inf_id not in allocated_ids:
                continue

            name = str(inf.get("name", "Creator"))
            platform = str(inf.get("platform", "social"))
            followers = int(inf.get("followers", 0))
            estimated_cost = float(inf.get("estimated_cost", 0.0))

            # Determine outreach channel
            if platform in ("instagram", "tiktok"):
                channel = "dm"
            else:
                channel = "email"

            # Build personalized subject
            subject = f"Partnership Opportunity — {campaign_name}"

            # Build message body
            deliverables = ", ".join(
                ct.replace("_", " ") for ct in content_types
            )
            follower_str = _format_followers(followers)

            message = (
                f"Hi {name},\n\n"
                f"We love your content in the {category} space and your "
                f"amazing community of {follower_str} followers on {platform.title()}.\n\n"
                f"We are launching our {campaign_name} and would love to "
                f"collaborate with you on {deliverables}.\n\n"
                f"Compensation: ${estimated_cost:,.0f} per deliverable set.\n\n"
                f"Would you be open to discussing this further?\n\n"
                f"Best regards"
            )

            templates.append({
                "influencer_id": inf_id,
                "influencer_name": name,
                "subject": subject,
                "message": message,
                "channel": channel,
            })

        return {
            "status": "success",
            "templates": templates,
        }
    except Exception as exc:
        return {
            "status": "error",
            "templates": [],
            "error": f"Outreach building failed: {exc}",
        }


def _format_followers(count: int) -> str:
    """Format follower count for display (e.g., 250K, 1.2M)."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    elif count >= 1_000:
        return f"{count / 1_000:.0f}K"
    return str(count)
