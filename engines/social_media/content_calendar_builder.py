"""Social Media Engine — content calendar builder.

Builds a weekly content calendar with post types, themes, and frequency
per platform.  Distributes content evenly across the week and avoids
platform fatigue.

Model note: Uses Qwen for structured calendar generation.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_FREQUENCY_MAP: dict[str, int] = {
    "daily": 7,
    "twice_daily": 14,
    "every_other_day": 4,
    "weekly": 1,
}

_THEMES_BY_GOAL: dict[str, list[str]] = {
    "engagement": [
        "behind_the_scenes", "poll_or_question", "user_generated_content",
        "product_highlight", "tip_or_tutorial", "meme_or_trend", "story_time",
    ],
    "awareness": [
        "brand_story", "product_launch", "collaboration", "industry_insight",
        "founder_spotlight", "values_showcase", "milestone",
    ],
    "traffic": [
        "blog_teaser", "product_link", "swipe_up_promo", "landing_page_push",
        "limited_offer", "new_arrival", "comparison",
    ],
    "conversions": [
        "product_demo", "testimonial", "before_after", "limited_time_offer",
        "bundle_deal", "social_proof", "urgency_post",
    ],
}

_DEFAULT_THEMES = ["product_highlight", "tip_or_tutorial", "behind_the_scenes",
                   "user_generated_content", "brand_story", "trend", "promotion"]

_TIME_SLOTS: dict[str, list[str]] = {
    "instagram": ["09:00", "12:00", "18:00", "21:00"],
    "facebook": ["09:00", "13:00", "16:00"],
    "tiktok": ["07:00", "12:00", "19:00", "22:00"],
    "pinterest": ["08:00", "14:00", "20:00"],
    "twitter": ["08:00", "12:00", "17:00"],
}

_DEFAULT_TIME_SLOTS = ["09:00", "13:00", "18:00"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_content_calendar(
    platforms: list[str],
    goal: str,
    posting_frequency: str,
    platform_analyses: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a weekly content calendar across all requested platforms.

    Args:
        platforms: Target platforms.
        goal: Campaign goal.
        posting_frequency: Desired frequency string.
        platform_analyses: Output from platform_analyzer (per-platform data).
        products: Product list for theme rotation.

    Returns:
        Structured dict with calendar entries and breakdown.
    """
    try:
        platforms = copy.deepcopy(platforms)
        themes = _THEMES_BY_GOAL.get(goal, _DEFAULT_THEMES)

        entries: list[dict[str, Any]] = []
        platform_breakdown: dict[str, int] = {}

        for platform_name in platforms:
            name = str(platform_name).lower().strip()

            # Determine posts per week for this platform
            base_frequency = _FREQUENCY_MAP.get(posting_frequency, 7)
            analysis = _find_analysis(platform_analyses, name)
            optimal_freq = analysis.get("optimal_post_frequency", base_frequency) if analysis else base_frequency
            posts_per_week = min(base_frequency, optimal_freq)
            posts_per_week = max(1, posts_per_week)

            # Get formats from analysis
            formats = analysis.get("best_formats", ["image", "video"]) if analysis else ["image", "video"]
            time_slots = _TIME_SLOTS.get(name, _DEFAULT_TIME_SLOTS)

            # Distribute posts across the week
            day_indices = _distribute_days(posts_per_week)
            for i, day_idx in enumerate(day_indices):
                entry: dict[str, Any] = {
                    "day": _DAYS[day_idx],
                    "platform": name,
                    "post_type": formats[i % len(formats)],
                    "theme": themes[i % len(themes)],
                    "time_slot": time_slots[i % len(time_slots)],
                }
                entries.append(entry)

            platform_breakdown[name] = posts_per_week

        total_posts = sum(platform_breakdown.values())

        return {
            "status": "success",
            "calendar": {
                "entries": entries,
                "total_posts_per_week": total_posts,
                "platform_breakdown": platform_breakdown,
                "model_note": "Qwen: structured content calendar generation",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "calendar": {},
            "error": f"Content calendar building failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _distribute_days(count: int) -> list[int]:
    """Distribute *count* posts evenly across the 7-day week.

    Returns a list of day indices (0=monday ... 6=sunday).
    """
    if count <= 0:
        return []
    if count >= 7:
        # Fill every day, then wrap
        return list(range(7)) + list(range(count - 7))
    step = 7 / count
    return [int(i * step) % 7 for i in range(count)]


def _find_analysis(
    analyses: list[dict[str, Any]],
    platform: str,
) -> dict[str, Any] | None:
    """Find the analysis dict for a specific platform."""
    for a in analyses:
        if a.get("platform") == platform:
            return a
    return None
