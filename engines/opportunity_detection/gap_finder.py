"""Opportunity Detection Engine — gap finder.

Finds market gaps by analyzing competitor coverage,
unmet demand signals, and underserved segments.
"""
from __future__ import annotations

import copy
from typing import Any


def find_gaps(
    market_data: dict[str, Any],
    competition: list[dict[str, Any]],
) -> dict[str, Any]:
    """Find market gaps from market and competition data.

    Args:
        market_data: Market size, segments, demand signals.
        competition: Competitor profiles and offerings.

    Returns:
        Structured dict with identified gaps.
    """
    try:
        mkt = copy.deepcopy(market_data)
        comps = copy.deepcopy(competition)

        gaps: list[dict[str, Any]] = []

        # Identify segments not covered by competitors
        market_segments = mkt.get("segments", [])
        competitor_segments: set[str] = set()
        for comp in comps:
            for seg in comp.get("segments_served", []):
                competitor_segments.add(str(seg).lower())

        for segment in market_segments:
            seg_name = str(segment.get("name", "")).lower()
            seg_size = float(segment.get("size", 0))
            seg_growth = float(segment.get("growth_rate", 0))

            if seg_name and seg_name not in competitor_segments:
                gaps.append({
                    "gap": f"Unserved segment: {segment.get('name', seg_name)}",
                    "segment": seg_name,
                    "market_size": seg_size,
                    "growth_rate": seg_growth,
                    "gap_type": "unserved_segment",
                })

        # Price gaps: segments where competitors only serve premium
        for segment in market_segments:
            seg_name = str(segment.get("name", "")).lower()
            price_range = segment.get("price_range", {})
            demand_low = float(price_range.get("budget_demand", 0))

            if demand_low > 0.3:
                comp_prices = []
                for comp in comps:
                    if seg_name in [s.lower() for s in comp.get("segments_served", [])]:
                        comp_prices.append(float(comp.get("avg_price", 0)))

                if comp_prices and min(comp_prices) > float(price_range.get("budget_ceiling", 50)):
                    gaps.append({
                        "gap": f"Price gap in {segment.get('name', seg_name)}: no budget option",
                        "segment": seg_name,
                        "market_size": round(float(segment.get("size", 0)) * demand_low, 2),
                        "growth_rate": 0.0,
                        "gap_type": "price_gap",
                    })

        # Feature gaps from market needs
        unmet_needs = mkt.get("unmet_needs", [])
        for need in unmet_needs:
            gaps.append({
                "gap": f"Unmet need: {need.get('description', str(need))}",
                "segment": str(need.get("segment", "general")),
                "market_size": float(need.get("estimated_value", 0)),
                "growth_rate": 0.0,
                "gap_type": "feature_gap",
            })

        return {
            "status": "success",
            "gaps": gaps,
            "total_gaps": len(gaps),
        }
    except Exception as exc:
        return {
            "status": "error",
            "gaps": [],
            "error": f"Gap finding failed: {exc}",
        }
