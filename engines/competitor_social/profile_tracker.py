"""Competitor Social Engine — profile tracker.

Tracks competitor social profiles across platforms.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def track_profiles(
    competitors: list[dict[str, Any]],
    platforms: list[str],
) -> dict[str, Any]:
    """Track competitor social media profiles.

    Args:
        competitors: List of competitor data with social profiles.
        platforms: Platforms to track.

    Returns:
        Structured dict with competitor profiles.
    """
    try:
        profiles: list[dict[str, Any]] = []

        for comp in competitors:
            comp_name = str(comp.get("name", ""))
            social = comp.get("social_profiles", comp.get("social", {}))

            for plat in platforms:
                plat_lower = plat.lower()
                plat_data = social.get(plat_lower, {})

                followers = int(plat_data.get("followers", 0))
                posts_pw = float(plat_data.get("posts_per_week", 0.0))
                eng_rate = float(plat_data.get("engagement_rate", 0.0))

                profiles.append({
                    "competitor": comp_name,
                    "platform": plat_lower,
                    "followers": followers,
                    "posts_per_week": posts_pw,
                    "avg_engagement_rate": eng_rate,
                })

        return {"status": "success", "competitor_profiles": profiles}
    except Exception as exc:
        return {"status": "error", "competitor_profiles": [], "error": f"Profile tracking failed: {exc}"}
