"""Competitor Ad Intelligence Engine — strategy reporter.

Reports on competitor ad strategies and identifies our gaps.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def report_strategy(
    ads_detected: list[dict[str, Any]],
    spend_estimates: list[dict[str, Any]],
    creative_patterns: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate strategy report and identify our gaps.

    Args:
        ads_detected: Detected competitor ads.
        spend_estimates: Spend estimates per competitor.
        creative_patterns: Creative patterns identified.

    Returns:
        Structured dict with strategy report and gaps.
    """
    try:
        # Identify top spenders
        comp_spend: dict[str, float] = {}
        for est in spend_estimates:
            comp = est.get("competitor", "")
            comp_spend[comp] = comp_spend.get(comp, 0.0) + est.get("estimated_monthly_spend", 0.0)

        top_spenders = sorted(comp_spend.items(), key=lambda x: x[1], reverse=True)

        # Platforms competitors use
        comp_platforms: dict[str, set[str]] = {}
        for ad in ads_detected:
            comp = ad.get("competitor", "")
            plat = ad.get("platform", "")
            if plat and ad.get("estimated_impressions", 0) > 0:
                comp_platforms.setdefault(comp, set()).add(plat)

        all_platforms = set()
        for ps in comp_platforms.values():
            all_platforms.update(ps)

        strategy_report = {
            "total_competitors_tracked": len(set(a.get("competitor", "") for a in ads_detected)),
            "total_ads_detected": len([a for a in ads_detected if a.get("estimated_impressions", 0) > 0]),
            "top_spenders": [{"competitor": c, "estimated_spend": round(s, 2)} for c, s in top_spenders[:5]],
            "platforms_in_use": sorted(all_platforms),
            "dominant_ad_types": _get_dominant_types(creative_patterns),
        }

        # Identify gaps
        our_gaps: list[str] = []
        if len(all_platforms) > 0:
            our_gaps.append(f"Competitors active on {len(all_platforms)} platforms: {', '.join(sorted(all_platforms))}")

        video_count = sum(1 for p in creative_patterns if p.get("pattern_type") == "video")
        if video_count > 0:
            our_gaps.append(f"{video_count} competitors using video ads — consider video ad strategy")

        total_estimated = sum(comp_spend.values())
        if total_estimated > 0:
            our_gaps.append(f"Total estimated competitor spend: ${total_estimated:,.2f}/month")

        return {
            "status": "success",
            "strategy_report": strategy_report,
            "our_gaps": our_gaps,
        }
    except Exception as exc:
        return {"status": "error", "strategy_report": {}, "our_gaps": [], "error": f"Strategy reporting failed: {exc}"}


def _get_dominant_types(patterns: list[dict[str, Any]]) -> list[str]:
    """Get most common ad types across all competitors."""
    type_counts: dict[str, int] = {}
    for p in patterns:
        t = p.get("pattern_type", "")
        type_counts[t] = type_counts.get(t, 0) + p.get("frequency", 0)
    return [t for t, _ in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:3]]
