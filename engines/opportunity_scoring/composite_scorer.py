"""Opportunity Scoring Engine — composite scorer.

Combines criteria, risk, and ROI into a final composite score.
Produces the ranked list and top recommendation.
"""
from __future__ import annotations

import copy
from typing import Any


def compute_composite(
    estimated: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute composite scores and produce final ranking.

    Args:
        estimated: ROI-estimated opportunities.

    Returns:
        Structured dict with scored and ranked opportunities.
    """
    try:
        opps = copy.deepcopy(estimated)
        scored: list[dict[str, Any]] = []

        for opp in opps:
            criteria_total = float(opp.get("criteria_total", 0.5))
            risk_score = float(opp.get("risk_score", 0.5))
            roi = float(opp.get("roi", 0))

            # Normalize ROI to 0-1 scale (cap at 500%)
            roi_norm = min(1.0, max(0, roi / 500))

            # Composite: high criteria + low risk + high ROI
            composite = round(
                criteria_total * 0.35 +
                (1.0 - risk_score) * 0.30 +
                roi_norm * 0.35,
                3,
            )

            scored.append({
                "opportunity": {
                    "gap": opp.get("gap", opp.get("description", "")),
                    "type": opp.get("type", opp.get("gap_type", "")),
                },
                "score": composite,
                "risk": str(opp.get("risk", "medium")),
                "roi": roi,
                "criteria_total": criteria_total,
                "risk_score": risk_score,
            })

        scored.sort(key=lambda s: s["score"], reverse=True)

        ranked_list = [s["opportunity"].get("gap", "") for s in scored]
        recommended = scored[0] if scored else {}

        return {
            "status": "success",
            "scored": scored,
            "ranked_list": ranked_list,
            "recommended": recommended,
            "total_scored": len(scored),
        }
    except Exception as exc:
        return {
            "status": "error",
            "scored": [],
            "error": f"Composite scoring failed: {exc}",
        }
