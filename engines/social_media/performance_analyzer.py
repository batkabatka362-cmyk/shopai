"""Social Media Engine — performance analyzer.

Analyzes past post performance: engagement rate, reach, follower growth,
and identifies best performing content types and platforms.  Produces
actionable recommendations.

Model note: Uses Mistral for analytical performance assessment.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Benchmark data (industry averages for comparison)
# ---------------------------------------------------------------------------

_BENCHMARKS: dict[str, dict[str, float]] = {
    "instagram": {"engagement_rate": 0.047, "reach_rate": 0.20, "growth_rate": 0.012},
    "facebook": {"engagement_rate": 0.025, "reach_rate": 0.05, "growth_rate": 0.005},
    "tiktok": {"engagement_rate": 0.078, "reach_rate": 0.40, "growth_rate": 0.025},
    "pinterest": {"engagement_rate": 0.020, "reach_rate": 0.15, "growth_rate": 0.008},
    "twitter": {"engagement_rate": 0.033, "reach_rate": 0.08, "growth_rate": 0.006},
}

_DEFAULT_BENCHMARK: dict[str, float] = {
    "engagement_rate": 0.035, "reach_rate": 0.15, "growth_rate": 0.010,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_performance(
    posts: list[dict[str, Any]],
    engagement_predictions: list[dict[str, Any]],
    platforms: list[str],
    past_performance: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze current and past post performance.

    Args:
        posts: Created post content.
        engagement_predictions: Per-post engagement predictions.
        platforms: Active platforms.
        past_performance: Historical performance records from memory.

    Returns:
        Structured dict with performance report and recommendations.
    """
    try:
        posts = copy.deepcopy(posts)
        engagement_predictions = copy.deepcopy(engagement_predictions)

        # Aggregate predicted engagement
        total_likes = 0
        total_comments = 0
        total_shares = 0
        total_saves = 0
        post_count = max(len(engagement_predictions), 1)

        platform_scores: dict[str, float] = {}
        type_scores: dict[str, float] = {}

        for pred in engagement_predictions:
            total_likes += pred.get("predicted_likes", 0)
            total_comments += pred.get("predicted_comments", 0)
            total_shares += pred.get("predicted_shares", 0)
            total_saves += pred.get("predicted_saves", 0)

            platform = pred.get("platform", "unknown")
            post_type = pred.get("post_type", "unknown")
            rate = pred.get("engagement_rate", 0.0)

            platform_scores[platform] = platform_scores.get(platform, 0.0) + rate
            type_scores[post_type] = type_scores.get(post_type, 0.0) + rate

        # Calculate averages
        avg_engagement_rate = round(
            sum(p.get("engagement_rate", 0.0) for p in engagement_predictions) / post_count,
            4,
        )

        # Estimate reach (simplified: likes * 10 as rough multiplier)
        reach_estimate = int(total_likes * 10)

        # Estimate follower growth from engagement
        follower_growth_rate = round(avg_engagement_rate * 0.25, 4)

        # Find best performing type and platform
        best_type = max(type_scores, key=type_scores.get) if type_scores else "unknown"  # type: ignore[arg-type]
        best_platform = max(platform_scores, key=platform_scores.get) if platform_scores else "unknown"  # type: ignore[arg-type]

        # Generate recommendations
        recommendations = _generate_recommendations(
            platforms, avg_engagement_rate, best_type, best_platform,
            engagement_predictions, past_performance,
        )

        report: dict[str, Any] = {
            "engagement_rate": avg_engagement_rate,
            "reach_estimate": reach_estimate,
            "follower_growth_rate": follower_growth_rate,
            "best_performing_type": best_type,
            "best_performing_platform": best_platform,
            "total_predicted_interactions": {
                "likes": total_likes,
                "comments": total_comments,
                "shares": total_shares,
                "saves": total_saves,
            },
            "recommendations": recommendations,
            "model_note": "Mistral: analytical performance assessment",
        }

        return {
            "status": "success",
            "report": report,
        }
    except Exception as exc:
        return {
            "status": "error",
            "report": {},
            "error": f"Performance analysis failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_recommendations(
    platforms: list[str],
    avg_engagement: float,
    best_type: str,
    best_platform: str,
    predictions: list[dict[str, Any]],
    past_performance: list[dict[str, Any]],
) -> list[str]:
    """Generate actionable recommendations based on performance data."""
    recs: list[str] = []

    # Compare to benchmarks
    for platform in platforms:
        benchmark = _BENCHMARKS.get(platform, _DEFAULT_BENCHMARK)
        if avg_engagement > benchmark["engagement_rate"]:
            recs.append(
                f"Strong performance on {platform} — engagement exceeds "
                f"industry average ({benchmark['engagement_rate']:.1%})."
            )
        else:
            recs.append(
                f"Consider optimizing {platform} content — engagement is below "
                f"industry average ({benchmark['engagement_rate']:.1%})."
            )

    # Best content type recommendation
    if best_type != "unknown":
        recs.append(f"Double down on '{best_type}' posts — they drive the highest engagement.")

    # Low-performing post types
    if predictions:
        low_performers = [
            p for p in predictions if p.get("engagement_rate", 0.0) < 0.03
        ]
        if low_performers:
            low_types = set(p.get("post_type", "unknown") for p in low_performers)
            recs.append(
                f"Review underperforming formats ({', '.join(low_types)}) — "
                "consider replacing with higher-engagement alternatives."
            )

    # Past performance trend
    if past_performance:
        past_rates = [p.get("engagement_rate", 0.0) for p in past_performance]
        avg_past = sum(past_rates) / len(past_rates) if past_rates else 0.0
        if avg_engagement > avg_past:
            recs.append("Positive trend: predicted engagement is improving over past performance.")
        elif avg_past > 0:
            recs.append("Engagement trend is flat or declining — consider refreshing content strategy.")

    return recs
