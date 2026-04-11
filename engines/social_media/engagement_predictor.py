"""Social Media Engine — engagement predictor.

Predicts likes, comments, shares, and saves for each platform based on
content type, posting time, platform characteristics, and goal alignment.

Model note: Uses Mistral for analytical engagement prediction.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Base engagement rates by platform (per 1000 followers)
# ---------------------------------------------------------------------------

_BASE_RATES: dict[str, dict[str, float]] = {
    "instagram": {"likes": 45.0, "comments": 3.5, "shares": 2.0, "saves": 5.0},
    "facebook": {"likes": 20.0, "comments": 4.0, "shares": 8.0, "saves": 1.5},
    "tiktok": {"likes": 80.0, "comments": 6.0, "shares": 12.0, "saves": 8.0},
    "pinterest": {"likes": 10.0, "comments": 0.5, "shares": 15.0, "saves": 25.0},
    "twitter": {"likes": 15.0, "comments": 2.0, "shares": 5.0, "saves": 1.0},
}

_DEFAULT_RATES: dict[str, float] = {"likes": 20.0, "comments": 2.0, "shares": 3.0, "saves": 2.0}


# ---------------------------------------------------------------------------
# Multipliers
# ---------------------------------------------------------------------------

_FORMAT_MULTIPLIERS: dict[str, float] = {
    "reels": 1.8, "short_video": 1.9, "carousel": 1.4, "video": 1.3,
    "story": 0.9, "live": 1.5, "duet": 1.6, "stitch": 1.5,
    "thread": 1.3, "poll": 1.4, "idea_pin": 1.2, "standard_pin": 1.0,
    "single_image": 1.0, "single_tweet": 0.9, "photo": 1.0,
    "link_post": 0.8, "event": 0.7, "space": 1.1,
    "video_pin": 1.3, "product_pin": 1.1, "quote_tweet": 1.1,
}

_TIME_MULTIPLIERS: dict[str, float] = {
    "07:00": 0.8, "08:00": 0.9, "09:00": 1.1, "12:00": 1.2,
    "13:00": 1.1, "14:00": 1.0, "16:00": 1.1, "17:00": 1.2,
    "18:00": 1.3, "19:00": 1.3, "20:00": 1.2, "21:00": 1.1,
    "22:00": 1.0,
}

_GOAL_BOOSTS: dict[str, dict[str, float]] = {
    "engagement": {"likes": 1.2, "comments": 1.4, "shares": 1.1, "saves": 1.1},
    "awareness": {"likes": 1.1, "comments": 0.9, "shares": 1.3, "saves": 1.0},
    "traffic": {"likes": 0.9, "comments": 0.8, "shares": 1.2, "saves": 1.3},
    "conversions": {"likes": 0.8, "comments": 0.7, "shares": 0.9, "saves": 1.5},
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def predict_engagement(
    posts: list[dict[str, Any]],
    calendar_entries: list[dict[str, Any]],
    goal: str,
    platform_analyses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Predict engagement metrics for each post.

    Args:
        posts: Created post content from post_creator.
        calendar_entries: Calendar entries (for time slot info).
        goal: Campaign goal.
        platform_analyses: Per-platform analysis data.

    Returns:
        Structured dict with per-platform engagement predictions.
    """
    try:
        posts = copy.deepcopy(posts)
        calendar_entries = copy.deepcopy(calendar_entries)

        predictions: list[dict[str, Any]] = []
        total_confidence = 0.0

        for i, post in enumerate(posts):
            platform = str(post.get("platform", "")).lower().strip()
            post_type = str(post.get("post_type", "image")).lower().strip()

            # Get time slot from corresponding calendar entry
            time_slot = "12:00"
            if i < len(calendar_entries):
                time_slot = str(calendar_entries[i].get("time_slot", "12:00"))

            # Base rates
            rates = _BASE_RATES.get(platform, _DEFAULT_RATES)

            # Apply multipliers
            format_mult = _FORMAT_MULTIPLIERS.get(post_type, 1.0)
            time_mult = _TIME_MULTIPLIERS.get(time_slot, 1.0)
            goal_boost = _GOAL_BOOSTS.get(goal, {})

            # Goal alignment from platform analysis
            goal_alignment = _get_goal_alignment(platform_analyses, platform)

            likes = rates["likes"] * format_mult * time_mult * goal_boost.get("likes", 1.0) * goal_alignment
            comments = rates["comments"] * format_mult * time_mult * goal_boost.get("comments", 1.0) * goal_alignment
            shares = rates["shares"] * format_mult * time_mult * goal_boost.get("shares", 1.0) * goal_alignment
            saves = rates["saves"] * format_mult * time_mult * goal_boost.get("saves", 1.0) * goal_alignment

            total_interactions = likes + comments + shares + saves
            engagement_rate = round(total_interactions / 1000.0, 4)

            # Confidence based on how much data we have
            confidence = _compute_confidence(platform, post_type, time_slot)
            total_confidence += confidence

            prediction: dict[str, Any] = {
                "platform": platform,
                "post_type": post_type,
                "predicted_likes": int(round(likes)),
                "predicted_comments": int(round(comments)),
                "predicted_shares": int(round(shares)),
                "predicted_saves": int(round(saves)),
                "engagement_rate": engagement_rate,
                "confidence": round(confidence, 2),
                "model_note": "Mistral: analytical engagement prediction",
            }
            predictions.append(prediction)

        overall_confidence = round(total_confidence / max(len(predictions), 1), 2)

        return {
            "status": "success",
            "predictions": predictions,
            "overall_confidence": overall_confidence,
        }
    except Exception as exc:
        return {
            "status": "error",
            "predictions": [],
            "overall_confidence": 0.0,
            "error": f"Engagement prediction failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_goal_alignment(
    analyses: list[dict[str, Any]],
    platform: str,
) -> float:
    """Get goal alignment score from platform analysis."""
    for a in analyses:
        if a.get("platform") == platform:
            return float(a.get("goal_alignment", 0.7))
    return 0.7


def _compute_confidence(platform: str, post_type: str, time_slot: str) -> float:
    """Compute prediction confidence based on data coverage."""
    score = 0.5

    if platform in _BASE_RATES:
        score += 0.2
    if post_type in _FORMAT_MULTIPLIERS:
        score += 0.15
    if time_slot in _TIME_MULTIPLIERS:
        score += 0.15

    return min(score, 1.0)
