"""Competitor Social Engine — engagement analyzer.

Analyzes engagement rates vs ours across platforms.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def analyze_engagement(
    competitor_profiles: list[dict[str, Any]],
    our_metrics: dict[str, Any],
    platforms: list[str],
) -> dict[str, Any]:
    """Compare our engagement rates against competitors.

    Args:
        competitor_profiles: Tracked competitor profiles.
        our_metrics: Our social metrics by platform.
        platforms: Platforms to compare.

    Returns:
        Structured dict with engagement comparison.
    """
    try:
        comparisons: list[dict[str, Any]] = []

        for plat in platforms:
            plat_lower = plat.lower()
            our_plat = our_metrics.get(plat_lower, {})
            our_rate = float(our_plat.get("engagement_rate", 0.0))

            plat_profiles = [p for p in competitor_profiles if p["platform"] == plat_lower]
            comp_rates = [(p["competitor"], p["avg_engagement_rate"]) for p in plat_profiles if p["avg_engagement_rate"] > 0]

            if not comp_rates:
                continue

            avg_comp_rate = round(sum(r for _, r in comp_rates) / len(comp_rates), 4)
            best_comp, best_rate = max(comp_rates, key=lambda x: x[1])

            # Rank ourselves
            all_rates = sorted([r for _, r in comp_rates] + [our_rate], reverse=True)
            our_rank = all_rates.index(our_rate) + 1

            comparisons.append({
                "platform": plat_lower,
                "our_rate": our_rate,
                "avg_competitor_rate": avg_comp_rate,
                "best_competitor": best_comp,
                "best_rate": best_rate,
                "our_rank": our_rank,
            })

        return {"status": "success", "engagement_comparison": comparisons}
    except Exception as exc:
        return {"status": "error", "engagement_comparison": [], "error": f"Engagement analysis failed: {exc}"}
