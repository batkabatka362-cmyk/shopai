"""Social Media Engine — platform analyzer.

Analyzes each platform's best practices, content formats, audience behavior,
and constraints.  Returns platform-specific guidance that downstream steps
use to tailor content.

Model note: Uses Mistral for analytical platform assessment.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Platform knowledge base
# ---------------------------------------------------------------------------

_PLATFORM_PROFILES: dict[str, dict[str, Any]] = {
    "instagram": {
        "best_formats": ["reels", "carousel", "story", "single_image"],
        "optimal_post_frequency": 7,
        "audience_behavior": "Visual-first; high engagement with reels and carousels. "
                             "Peak activity evenings and weekends.",
        "key_features": ["reels", "stories", "shopping_tags", "collab_posts", "guides"],
        "character_limit": 2200,
        "hashtag_limit": 30,
    },
    "facebook": {
        "best_formats": ["video", "link_post", "photo", "live", "event"],
        "optimal_post_frequency": 5,
        "audience_behavior": "Community-driven; shares and group posts amplify reach. "
                             "Peak activity midday and early evening.",
        "key_features": ["groups", "marketplace", "events", "live_video", "stories"],
        "character_limit": 63206,
        "hashtag_limit": 10,
    },
    "tiktok": {
        "best_formats": ["short_video", "duet", "stitch", "live"],
        "optimal_post_frequency": 10,
        "audience_behavior": "Trend-driven; algorithm rewards watch time and engagement. "
                             "Active throughout the day, peaks late evening.",
        "key_features": ["trends", "sounds", "effects", "duets", "stitches", "live"],
        "character_limit": 4000,
        "hashtag_limit": 5,
    },
    "pinterest": {
        "best_formats": ["standard_pin", "idea_pin", "video_pin", "product_pin"],
        "optimal_post_frequency": 15,
        "audience_behavior": "Search and save oriented; evergreen content performs well. "
                             "Users plan ahead — seasonal spikes matter.",
        "key_features": ["boards", "rich_pins", "idea_pins", "shopping", "trends"],
        "character_limit": 500,
        "hashtag_limit": 20,
    },
    "twitter": {
        "best_formats": ["thread", "single_tweet", "poll", "space", "quote_tweet"],
        "optimal_post_frequency": 14,
        "audience_behavior": "Real-time conversation; threads and hashtags drive discovery. "
                             "Peak activity mornings and lunch hours.",
        "key_features": ["threads", "hashtags", "spaces", "polls", "communities"],
        "character_limit": 280,
        "hashtag_limit": 3,
    },
}

_DEFAULT_PROFILE: dict[str, Any] = {
    "best_formats": ["image", "video", "text"],
    "optimal_post_frequency": 5,
    "audience_behavior": "General social media audience.",
    "key_features": ["posts", "stories"],
    "character_limit": 2000,
    "hashtag_limit": 10,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_platforms(
    platforms: list[str],
    goal: str,
    brand_voice: str,
) -> dict[str, Any]:
    """Analyze each requested platform and return best-practice guidance.

    Args:
        platforms: List of platform names to analyze.
        goal: Campaign goal (engagement, awareness, traffic, conversions).
        brand_voice: Brand voice descriptor.

    Returns:
        Structured dict with per-platform analysis results.
    """
    try:
        platforms = copy.deepcopy(platforms)
        analyses: list[dict[str, Any]] = []

        for platform_name in platforms:
            name = str(platform_name).lower().strip()
            profile = _PLATFORM_PROFILES.get(name, _DEFAULT_PROFILE)

            # Adjust frequency recommendation based on goal
            frequency = profile["optimal_post_frequency"]
            if goal == "engagement":
                frequency = max(frequency, 7)
            elif goal == "awareness":
                frequency = int(frequency * 1.2)
            elif goal == "conversions":
                frequency = max(3, frequency - 2)

            analysis: dict[str, Any] = {
                "platform": name,
                "best_formats": list(profile["best_formats"]),
                "optimal_post_frequency": frequency,
                "audience_behavior": profile["audience_behavior"],
                "key_features": list(profile["key_features"]),
                "character_limit": profile["character_limit"],
                "hashtag_limit": profile["hashtag_limit"],
                "goal_alignment": _score_goal_alignment(name, goal),
                "voice_fit": _score_voice_fit(name, brand_voice),
                "model_note": "Mistral: analytical platform assessment",
            }
            analyses.append(analysis)

        return {
            "status": "success",
            "analyses": analyses,
        }
    except Exception as exc:
        return {
            "status": "error",
            "analyses": [],
            "error": f"Platform analysis failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _score_goal_alignment(platform: str, goal: str) -> float:
    """Score how well a platform aligns with the campaign goal (0-1)."""
    alignment: dict[str, dict[str, float]] = {
        "instagram": {"engagement": 0.95, "awareness": 0.85, "traffic": 0.60, "conversions": 0.75},
        "facebook": {"engagement": 0.70, "awareness": 0.80, "traffic": 0.85, "conversions": 0.80},
        "tiktok": {"engagement": 0.90, "awareness": 0.95, "traffic": 0.40, "conversions": 0.45},
        "pinterest": {"engagement": 0.50, "awareness": 0.70, "traffic": 0.90, "conversions": 0.85},
        "twitter": {"engagement": 0.80, "awareness": 0.75, "traffic": 0.70, "conversions": 0.40},
    }
    return alignment.get(platform, {}).get(goal, 0.50)


def _score_voice_fit(platform: str, voice: str) -> float:
    """Score how well a brand voice fits a platform (0-1)."""
    fit: dict[str, dict[str, float]] = {
        "instagram": {"playful": 0.90, "professional": 0.70, "bold": 0.85, "minimal": 0.80},
        "facebook": {"playful": 0.75, "professional": 0.85, "bold": 0.70, "minimal": 0.60},
        "tiktok": {"playful": 0.95, "professional": 0.40, "bold": 0.90, "minimal": 0.50},
        "pinterest": {"playful": 0.65, "professional": 0.75, "bold": 0.60, "minimal": 0.90},
        "twitter": {"playful": 0.85, "professional": 0.80, "bold": 0.90, "minimal": 0.70},
    }
    voice_lower = str(voice).lower().strip()
    return fit.get(platform, {}).get(voice_lower, 0.60)
