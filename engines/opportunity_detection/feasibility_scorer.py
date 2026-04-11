"""Opportunity Detection Engine — feasibility scorer.

Scores feasibility of each opportunity based on resource
requirements, technical complexity, and time to market.
"""
from __future__ import annotations

import copy
from typing import Any


def score_feasibility(
    matched_gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score feasibility for each matched gap.

    Args:
        matched_gaps: Demand-matched gaps.

    Returns:
        Structured dict with feasibility scores.
    """
    try:
        gaps = copy.deepcopy(matched_gaps)
        scored: list[dict[str, Any]] = []

        for gap in gaps:
            gap_type = gap.get("gap_type", "unknown")
            market_size = float(gap.get("market_size", 0))
            demand = float(gap.get("demand_score", 0))

            # Base feasibility by gap type
            type_scores = {
                "price_gap": 0.8,       # Easy: just price differently
                "unserved_segment": 0.5,  # Medium: new market entry
                "feature_gap": 0.4,       # Harder: development needed
            }
            base = type_scores.get(gap_type, 0.5)

            # Adjust for market size (larger = more feasible, more resources)
            size_factor = min(0.2, market_size / 5000000) if market_size > 0 else 0.0

            # Adjust for demand (higher demand = more feasible)
            demand_factor = demand * 0.2

            feasibility = round(min(1.0, base + size_factor + demand_factor), 3)

            gap["feasibility"] = feasibility
            scored.append(gap)

        scored.sort(key=lambda g: g["feasibility"], reverse=True)

        return {
            "status": "success",
            "scored": scored,
            "total_scored": len(scored),
        }
    except Exception as exc:
        return {
            "status": "error",
            "scored": [],
            "error": f"Feasibility scoring failed: {exc}",
        }
