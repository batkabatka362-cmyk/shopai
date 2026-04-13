"""Social Media Engine — trend tracker.

Tracks trending topics, sounds, formats, and challenges per platform.
Returns relevance-scored trending items that downstream steps can use
to align content with current trends.

Model note: no model usage — deterministic trend catalogue.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Trending catalogue (simulated real-time data)
# ---------------------------------------------------------------------------

_TRENDING_DATA: dict[str, list[dict[str, Any]]] = {
    "instagram": [
        {"topic": "carousel storytelling", "category": "format", "base_score": 0.92},
        {"topic": "behind-the-scenes reels", "category": "format", "base_score": 0.89},
        {"topic": "collaboration posts", "category": "format", "base_score": 0.85},
        {"topic": "mini vlogs", "category": "format", "base_score": 0.83},
        {"topic": "trending audio clips", "category": "sound", "base_score": 0.88},
        {"topic": "aesthetic flat lays", "category": "format", "base_score": 0.80},
        {"topic": "day in my life", "category": "hashtag", "base_score": 0.78},
    ],
    "facebook": [
        {"topic": "live shopping events", "category": "format", "base_score": 0.87},
        {"topic": "community polls", "category": "format", "base_score": 0.82},
        {"topic": "group discussions", "category": "format", "base_score": 0.80},
        {"topic": "video testimonials", "category": "format", "base_score": 0.78},
        {"topic": "event marketing", "category": "format", "base_score": 0.75},
    ],
    "tiktok": [
        {"topic": "get ready with me", "category": "format", "base_score": 0.95},
        {"topic": "trending sounds", "category": "sound", "base_score": 0.94},
        {"topic": "silent reviews", "category": "format", "base_score": 0.90},
        {"topic": "POV storytelling", "category": "format", "base_score": 0.88},
        {"topic": "brand challenges", "category": "challenge", "base_score": 0.92},
        {"topic": "ASMR unboxing", "category": "sound", "base_score": 0.86},
        {"topic": "transition edits", "category": "format", "base_score": 0.84},
        {"topic": "duet reactions", "category": "format", "base_score": 0.82},
    ],
    "pinterest": [
        {"topic": "step-by-step idea pins", "category": "format", "base_score": 0.88},
        {"topic": "seasonal planning boards", "category": "format", "base_score": 0.85},
        {"topic": "minimalist aesthetics", "category": "hashtag", "base_score": 0.83},
        {"topic": "DIY projects", "category": "format", "base_score": 0.80},
        {"topic": "product roundups", "category": "format", "base_score": 0.78},
    ],
    "twitter": [
        {"topic": "thought leadership threads", "category": "format", "base_score": 0.90},
        {"topic": "hot takes", "category": "format", "base_score": 0.85},
        {"topic": "meme marketing", "category": "format", "base_score": 0.83},
        {"topic": "poll engagement", "category": "format", "base_score": 0.80},
        {"topic": "spaces discussions", "category": "format", "base_score": 0.77},
    ],
}

# ---------------------------------------------------------------------------
# Goal relevance adjustments
# ---------------------------------------------------------------------------

_CATEGORY_GOAL_BOOST: dict[str, dict[str, float]] = {
    "engagement": {"format": 1.1, "sound": 1.05, "challenge": 1.2, "hashtag": 1.0},
    "awareness": {"format": 1.0, "sound": 1.1, "challenge": 1.15, "hashtag": 1.1},
    "traffic": {"format": 0.95, "sound": 0.9, "challenge": 0.85, "hashtag": 1.1},
    "conversions": {"format": 1.0, "sound": 0.85, "challenge": 0.9, "hashtag": 1.05},
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def track_trends(
    platforms: list[str],
    goal: str,
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Track trending topics and formats across requested platforms.

    Args:
        platforms: Target platforms to scan.
        goal: Campaign goal for relevance scoring.
        products: Product list for category matching.

    Returns:
        Structured dict with trending items scored by relevance.
    """
    try:
        platforms = copy.deepcopy(platforms)

        product_categories = _extract_categories(products)
        goal_boosts = _CATEGORY_GOAL_BOOST.get(goal, {})

        trending_items: list[dict[str, Any]] = []

        for platform_name in platforms:
            name = str(platform_name).lower().strip()
            platform_trends = _TRENDING_DATA.get(name, [])

            for trend in platform_trends:
                category = trend.get("category", "format")
                base_score = trend.get("base_score", 0.5)

                # Apply goal boost
                boost = goal_boosts.get(category, 1.0)
                relevance = round(min(base_score * boost, 1.0), 2)

                item: dict[str, Any] = {
                    "platform": name,
                    "topic": trend["topic"],
                    "category": category,
                    "relevance_score": relevance,
                }
                trending_items.append(item)

        # Sort by relevance descending
        trending_items.sort(key=lambda t: t["relevance_score"], reverse=True)

        return {
            "status": "success",
            "trending": trending_items,
        }
    except Exception as exc:
        return {
            "status": "error",
            "trending": [],
            "error": f"Trend tracking failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_categories(products: list[dict[str, Any]]) -> list[str]:
    """Extract unique product categories."""
    categories: list[str] = []
    seen: set[str] = set()
    for p in products:
        cat = str(p.get("category", "")).lower().strip()
        if cat and cat not in seen:
            categories.append(cat)
            seen.add(cat)
    return categories
