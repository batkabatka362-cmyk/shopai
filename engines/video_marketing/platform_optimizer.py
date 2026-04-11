"""Video Marketing Engine — platform optimizer.

Optimizes video specifications for target platforms (TikTok, YouTube,
Instagram). Provides aspect ratio, resolution, hashtag, and timing
recommendations.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Platform specifications
# ---------------------------------------------------------------------------

_PLATFORM_SPECS: dict[str, dict[str, Any]] = {
    "tiktok": {
        "aspect_ratio": "9:16",
        "max_duration": 180,
        "min_resolution": "720p",
        "recommended_hashtags": ["#fyp", "#foryou", "#tiktokshop", "#trending"],
        "best_posting_times": ["7:00 AM", "12:00 PM", "7:00 PM"],
    },
    "youtube": {
        "aspect_ratio": "16:9",
        "max_duration": 600,
        "min_resolution": "1080p",
        "recommended_hashtags": ["#shorts", "#review", "#howto"],
        "best_posting_times": ["2:00 PM", "4:00 PM", "9:00 PM"],
    },
    "youtube_shorts": {
        "aspect_ratio": "9:16",
        "max_duration": 60,
        "min_resolution": "1080p",
        "recommended_hashtags": ["#shorts", "#viral"],
        "best_posting_times": ["12:00 PM", "5:00 PM", "8:00 PM"],
    },
    "instagram_reels": {
        "aspect_ratio": "9:16",
        "max_duration": 90,
        "min_resolution": "720p",
        "recommended_hashtags": ["#reels", "#instagood", "#explore"],
        "best_posting_times": ["11:00 AM", "1:00 PM", "7:00 PM"],
    },
    "instagram_feed": {
        "aspect_ratio": "1:1",
        "max_duration": 60,
        "min_resolution": "720p",
        "recommended_hashtags": ["#instadaily", "#productreview"],
        "best_posting_times": ["11:00 AM", "2:00 PM", "7:00 PM"],
    },
    "facebook": {
        "aspect_ratio": "16:9",
        "max_duration": 240,
        "min_resolution": "720p",
        "recommended_hashtags": [],
        "best_posting_times": ["1:00 PM", "3:00 PM", "9:00 PM"],
    },
}

_DEFAULT_SPECS: dict[str, Any] = {
    "aspect_ratio": "16:9",
    "max_duration": 300,
    "min_resolution": "720p",
    "recommended_hashtags": [],
    "best_posting_times": ["12:00 PM"],
}


def optimize_for_platform(
    platform: str,
    duration_seconds: int,
    product: dict[str, Any],
) -> dict[str, Any]:
    """Get platform-specific optimization specs.

    Args:
        platform: Target platform name.
        duration_seconds: Intended video duration.
        product: Product info dict.

    Returns:
        Structured dict with platform specs and adjustments.
    """
    try:
        platform_lower = platform.lower().replace(" ", "_")
        specs = _PLATFORM_SPECS.get(platform_lower, _DEFAULT_SPECS)

        max_dur = int(specs["max_duration"])
        category = str(product.get("category", ""))
        product_name = str(product.get("title", ""))

        # Build product-specific hashtags
        hashtags = list(specs.get("recommended_hashtags", []))
        if category:
            hashtags.append(f"#{category.lower().replace(' ', '')}")
        if product_name:
            clean_name = product_name.lower().replace(" ", "")[:20]
            hashtags.append(f"#{clean_name}")

        # Check duration compliance
        warnings: list[str] = []
        if duration_seconds > max_dur:
            warnings.append(
                f"Duration {duration_seconds}s exceeds {platform} max of {max_dur}s"
            )

        return {
            "status": "success",
            "platform_specs": {
                "platform": platform,
                "aspect_ratio": str(specs["aspect_ratio"]),
                "max_duration": max_dur,
                "min_resolution": str(specs["min_resolution"]),
                "recommended_hashtags": hashtags,
                "best_posting_times": list(specs["best_posting_times"]),
            },
            "warnings": warnings,
        }
    except Exception as exc:
        return {
            "status": "error",
            "platform_specs": {},
            "error": f"Platform optimization failed: {exc}",
        }
