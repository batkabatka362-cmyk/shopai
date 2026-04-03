"""Influencer Engine — influencer finder.

Finds relevant influencers by niche and audience criteria.
Generates candidate list based on category, platform, and budget fit.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Simulated influencer database (in production, this queries an API)
# ---------------------------------------------------------------------------

_INFLUENCER_DB: list[dict[str, Any]] = [
    {"id": "inf_001", "name": "StyleGuru", "platform": "instagram", "followers": 250000, "niche": "fashion", "engagement_rate": 3.2, "avg_views": 45000, "location": "US", "cpm": 12.0},
    {"id": "inf_002", "name": "TechReviewer", "platform": "youtube", "followers": 500000, "niche": "tech", "engagement_rate": 4.5, "avg_views": 120000, "location": "US", "cpm": 18.0},
    {"id": "inf_003", "name": "FitLifePro", "platform": "instagram", "followers": 180000, "niche": "fitness", "engagement_rate": 5.1, "avg_views": 30000, "location": "US", "cpm": 10.0},
    {"id": "inf_004", "name": "BeautyInsider", "platform": "tiktok", "followers": 800000, "niche": "beauty", "engagement_rate": 6.8, "avg_views": 200000, "location": "UK", "cpm": 8.0},
    {"id": "inf_005", "name": "HomeDecorQueen", "platform": "instagram", "followers": 120000, "niche": "home", "engagement_rate": 4.0, "avg_views": 20000, "location": "US", "cpm": 9.0},
    {"id": "inf_006", "name": "FoodieAdventures", "platform": "youtube", "followers": 350000, "niche": "food", "engagement_rate": 3.8, "avg_views": 80000, "location": "US", "cpm": 15.0},
    {"id": "inf_007", "name": "GadgetNerd", "platform": "youtube", "followers": 220000, "niche": "tech", "engagement_rate": 5.2, "avg_views": 60000, "location": "CA", "cpm": 14.0},
    {"id": "inf_008", "name": "MiniStyle", "platform": "tiktok", "followers": 450000, "niche": "fashion", "engagement_rate": 7.2, "avg_views": 150000, "location": "US", "cpm": 7.0},
    {"id": "inf_009", "name": "WellnessWave", "platform": "instagram", "followers": 95000, "niche": "health", "engagement_rate": 4.8, "avg_views": 18000, "location": "AU", "cpm": 11.0},
    {"id": "inf_010", "name": "OutdoorExplorer", "platform": "youtube", "followers": 300000, "niche": "outdoor", "engagement_rate": 3.5, "avg_views": 70000, "location": "US", "cpm": 13.0},
]

# Category-to-niche mapping for broad matching
_CATEGORY_NICHE_MAP: dict[str, list[str]] = {
    "fashion": ["fashion", "beauty", "lifestyle"],
    "tech": ["tech", "gadgets"],
    "fitness": ["fitness", "health", "wellness"],
    "beauty": ["beauty", "fashion", "lifestyle"],
    "home": ["home", "lifestyle"],
    "food": ["food", "lifestyle"],
    "health": ["health", "fitness", "wellness"],
    "outdoor": ["outdoor", "fitness"],
}


def find_influencers(
    category: str,
    target_audience: dict[str, Any],
    budget: float,
) -> dict[str, Any]:
    """Find relevant influencer candidates.

    Args:
        category: Product/brand category.
        target_audience: TargetAudience dict with preferences.
        budget: Total campaign budget.

    Returns:
        Structured dict with influencer candidates.
    """
    try:
        category_lower = category.lower().strip()
        relevant_niches = _CATEGORY_NICHE_MAP.get(category_lower, [category_lower])
        preferred_platforms = [
            p.lower() for p in target_audience.get("platforms", [])
        ]
        preferred_geos = [
            g.upper() for g in target_audience.get("geography", [])
        ]

        candidates: list[dict[str, Any]] = []

        for inf in _INFLUENCER_DB:
            inf = copy.deepcopy(inf)
            niche = str(inf.get("niche", "")).lower()

            # Niche match
            if niche not in relevant_niches and category_lower not in niche:
                continue

            # Platform filter (if specified)
            platform = str(inf.get("platform", "")).lower()
            if preferred_platforms and platform not in preferred_platforms:
                continue

            # Geography filter (if specified)
            location = str(inf.get("location", "")).upper()
            if preferred_geos and location not in preferred_geos:
                continue

            # Budget feasibility: estimated cost should be within budget
            followers = int(inf.get("followers", 0))
            cpm = float(inf.get("cpm", 10.0))
            estimated_post_cost = round((followers / 1000.0) * cpm, 2)
            if estimated_post_cost > budget:
                continue

            candidates.append({
                "id": inf["id"],
                "name": inf["name"],
                "platform": inf["platform"],
                "followers": followers,
                "niche": niche,
                "engagement_rate": inf["engagement_rate"],
                "avg_views": inf["avg_views"],
                "location": location,
            })

        return {
            "status": "success",
            "candidates": candidates,
        }
    except Exception as exc:
        return {
            "status": "error",
            "candidates": [],
            "error": f"Influencer finding failed: {exc}",
        }
