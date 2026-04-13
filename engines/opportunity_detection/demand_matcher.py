"""Opportunity Detection Engine — demand matcher.

Matches identified gaps to demand signals: search volume,
customer requests, trend data, and social mentions.
"""
from __future__ import annotations

import copy
from typing import Any


def match_demand(
    gaps: list[dict[str, Any]],
    trends: list[dict[str, Any]],
) -> dict[str, Any]:
    """Match gaps to demand signals.

    Args:
        gaps: Identified market gaps.
        trends: Trend data and demand signals.

    Returns:
        Structured dict with demand-matched gaps.
    """
    try:
        gap_data = copy.deepcopy(gaps)
        trend_data = copy.deepcopy(trends)

        # Build trend lookup by keyword
        trend_map: dict[str, float] = {}
        for trend in trend_data:
            keywords = trend.get("keywords", [])
            strength = float(trend.get("strength", trend.get("score", 0.5)))
            for kw in keywords:
                trend_map[str(kw).lower()] = max(
                    trend_map.get(str(kw).lower(), 0),
                    strength,
                )

        matched: list[dict[str, Any]] = []

        for gap in gap_data:
            gap_text = str(gap.get("gap", "")).lower()
            segment = str(gap.get("segment", "")).lower()

            # Calculate demand score from trend matching
            demand_score = 0.0
            matching_trends = 0

            for keyword, strength in trend_map.items():
                if keyword in gap_text or keyword in segment:
                    demand_score = max(demand_score, strength)
                    matching_trends += 1

            # Factor in market size
            market_size = float(gap.get("market_size", 0))
            if market_size > 0:
                demand_score = min(1.0, demand_score + min(market_size / 1000000, 0.3))

            gap["demand_score"] = round(demand_score, 3)
            gap["matching_trends"] = matching_trends
            matched.append(gap)

        # Sort by demand score
        matched.sort(key=lambda g: g["demand_score"], reverse=True)

        return {
            "status": "success",
            "matched": matched,
            "total_matched": len(matched),
        }
    except Exception as exc:
        return {
            "status": "error",
            "matched": [],
            "error": f"Demand matching failed: {exc}",
        }
