"""Opportunity Detection Engine — priority ranker.

Ranks opportunities by ROI potential: combines demand,
feasibility, market size, and growth rate into a priority score.
"""
from __future__ import annotations

import copy
from typing import Any


def rank_priorities(
    scored_gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Rank opportunities by priority.

    Args:
        scored_gaps: Feasibility-scored gaps.

    Returns:
        Structured dict with ranked opportunities.
    """
    try:
        gaps = copy.deepcopy(scored_gaps)
        ranked: list[dict[str, Any]] = []

        for gap in gaps:
            demand = float(gap.get("demand_score", 0))
            feasibility = float(gap.get("feasibility", 0))
            market_size = float(gap.get("market_size", 0))
            growth = float(gap.get("growth_rate", 0))

            # Composite priority score
            priority_score = round(
                demand * 0.3 +
                feasibility * 0.3 +
                min(1.0, market_size / 1000000) * 0.25 +
                min(1.0, growth * 5) * 0.15,
                3,
            )

            if priority_score >= 0.7:
                priority = "high"
            elif priority_score >= 0.4:
                priority = "medium"
            else:
                priority = "low"

            ranked.append({
                "gap": gap.get("gap", ""),
                "demand": demand,
                "feasibility": feasibility,
                "priority": priority,
                "priority_score": priority_score,
                "market_size": market_size,
            })

        ranked.sort(key=lambda r: r["priority_score"], reverse=True)

        top_opportunity = ranked[0] if ranked else {}

        return {
            "status": "success",
            "ranked": ranked,
            "top_opportunity": top_opportunity,
            "total_ranked": len(ranked),
        }
    except Exception as exc:
        return {
            "status": "error",
            "ranked": [],
            "error": f"Priority ranking failed: {exc}",
        }
