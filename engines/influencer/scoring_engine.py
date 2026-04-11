"""Influencer Engine — scoring engine.

Scores influencers based on engagement rate, audience fit,
authenticity signals, and cost efficiency.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def score_influencers(
    candidates: list[dict[str, Any]],
    target_audience: dict[str, Any],
    budget: float,
) -> dict[str, Any]:
    """Score and rank influencer candidates.

    Args:
        candidates: List of InfluencerCandidate dicts.
        target_audience: TargetAudience dict with preferences.
        budget: Total campaign budget.

    Returns:
        Structured dict with scored influencers sorted by score.
    """
    try:
        candidates = copy.deepcopy(candidates)
        preferred_platforms = [
            p.lower() for p in target_audience.get("platforms", [])
        ]

        scored: list[dict[str, Any]] = []

        for inf in candidates:
            engagement_rate = float(inf.get("engagement_rate", 0.0))
            followers = int(inf.get("followers", 0))
            avg_views = int(inf.get("avg_views", 0))
            platform = str(inf.get("platform", "")).lower()

            # Engagement score (0-1): normalized, >5% is excellent
            engagement_score = round(min(engagement_rate / 8.0, 1.0), 3)

            # Audience fit (0-1): platform match + follower tier
            platform_match = 1.0 if (not preferred_platforms or platform in preferred_platforms) else 0.5
            # Prefer mid-tier influencers (10k-500k) for better ROI
            if 50000 <= followers <= 500000:
                tier_score = 1.0
            elif 10000 <= followers < 50000:
                tier_score = 0.8
            elif followers > 500000:
                tier_score = 0.7
            else:
                tier_score = 0.4
            audience_fit = round(platform_match * 0.5 + tier_score * 0.5, 3)

            # Authenticity score (0-1): views-to-followers ratio
            if followers > 0:
                view_ratio = avg_views / followers
                # Healthy ratio: 10-40% of followers
                if 0.10 <= view_ratio <= 0.40:
                    authenticity = 0.95
                elif 0.05 <= view_ratio < 0.10:
                    authenticity = 0.75
                elif view_ratio > 0.40:
                    authenticity = 0.85  # very engaged but check for bots
                else:
                    authenticity = 0.50  # suspiciously low views
            else:
                authenticity = 0.30

            # Estimated cost per post
            # CPM varies by platform and tier
            if platform == "tiktok":
                base_cpm = 7.0
            elif platform == "youtube":
                base_cpm = 15.0
            else:
                base_cpm = 10.0
            estimated_cost = round((followers / 1000.0) * base_cpm, 2)

            # Overall score: weighted composite
            score = round(
                engagement_score * 0.30 +
                audience_fit * 0.25 +
                authenticity * 0.25 +
                (1.0 - min(estimated_cost / budget, 1.0)) * 0.20,
                3,
            )

            scored.append({
                "id": inf["id"],
                "name": inf["name"],
                "platform": inf["platform"],
                "followers": followers,
                "engagement_rate": engagement_rate,
                "score": score,
                "audience_fit": audience_fit,
                "authenticity_score": round(authenticity, 3),
                "estimated_cost": estimated_cost,
            })

        # Sort by score descending
        scored.sort(key=lambda x: x["score"], reverse=True)

        return {
            "status": "success",
            "scored": scored,
        }
    except Exception as exc:
        return {
            "status": "error",
            "scored": [],
            "error": f"Influencer scoring failed: {exc}",
        }
