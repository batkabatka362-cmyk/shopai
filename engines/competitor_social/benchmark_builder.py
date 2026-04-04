"""Competitor Social Engine — benchmark builder.

Builds social benchmarks and generates recommendations.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def build_benchmarks(
    competitor_profiles: list[dict[str, Any]],
    engagement_comparison: list[dict[str, Any]],
    our_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Build social media benchmarks and recommendations.

    Args:
        competitor_profiles: Tracked competitor profiles.
        engagement_comparison: Engagement comparison data.
        our_metrics: Our social metrics.

    Returns:
        Structured dict with benchmarks and recommendations.
    """
    try:
        # Aggregate metrics
        all_followers = [p["followers"] for p in competitor_profiles if p["followers"] > 0]
        all_eng_rates = [p["avg_engagement_rate"] for p in competitor_profiles if p["avg_engagement_rate"] > 0]
        all_post_freq = [p["posts_per_week"] for p in competitor_profiles if p["posts_per_week"] > 0]

        our_total_followers = sum(
            int(v.get("followers", 0)) for v in our_metrics.values() if isinstance(v, dict)
        )
        our_avg_eng = 0.0
        eng_vals = [float(v.get("engagement_rate", 0)) for v in our_metrics.values() if isinstance(v, dict) and v.get("engagement_rate")]
        if eng_vals:
            our_avg_eng = sum(eng_vals) / len(eng_vals)

        benchmarks: list[dict[str, Any]] = []

        if all_followers:
            avg_f = sum(all_followers) / len(all_followers)
            top_f = max(all_followers)
            pct = sum(1 for f in all_followers if our_total_followers > f) * 100 // len(all_followers) if all_followers else 0
            benchmarks.append({
                "metric": "followers",
                "our_value": float(our_total_followers),
                "industry_avg": round(avg_f, 0),
                "top_performer": float(top_f),
                "percentile": pct,
            })

        if all_eng_rates:
            avg_e = sum(all_eng_rates) / len(all_eng_rates)
            top_e = max(all_eng_rates)
            pct = sum(1 for e in all_eng_rates if our_avg_eng > e) * 100 // len(all_eng_rates) if all_eng_rates else 0
            benchmarks.append({
                "metric": "engagement_rate",
                "our_value": round(our_avg_eng, 4),
                "industry_avg": round(avg_e, 4),
                "top_performer": top_e,
                "percentile": pct,
            })

        if all_post_freq:
            avg_p = sum(all_post_freq) / len(all_post_freq)
            top_p = max(all_post_freq)
            our_post_freq = float(our_metrics.get("posts_per_week", 0))
            pct = sum(1 for p in all_post_freq if our_post_freq > p) * 100 // len(all_post_freq) if all_post_freq else 0
            benchmarks.append({
                "metric": "posting_frequency",
                "our_value": our_post_freq,
                "industry_avg": round(avg_p, 1),
                "top_performer": top_p,
                "percentile": pct,
            })

        # Recommendations
        recommendations: list[str] = []
        for comp in engagement_comparison:
            if comp.get("our_rank", 1) > 3:
                recommendations.append(
                    f"Improve engagement on {comp['platform']} — currently ranked #{comp['our_rank']}"
                )
            if comp.get("our_rate", 0) < comp.get("avg_competitor_rate", 0) * 0.5:
                recommendations.append(
                    f"Engagement on {comp['platform']} is below 50% of competitor average — review content strategy"
                )

        for bm in benchmarks:
            if bm["percentile"] < 25:
                recommendations.append(
                    f"{bm['metric']} is in bottom 25% — prioritize improvement"
                )

        if not recommendations:
            recommendations.append("Social presence is competitive — maintain current strategy and test new formats")

        return {
            "status": "success",
            "benchmarks": benchmarks,
            "recommendations": recommendations,
        }
    except Exception as exc:
        return {"status": "error", "benchmarks": [], "recommendations": [], "error": f"Benchmark building failed: {exc}"}
