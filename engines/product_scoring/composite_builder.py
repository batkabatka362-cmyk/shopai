"""Product Scoring Engine — composite builder.

Combines demand, margin, and competition scores into a weighted composite
score and assigns tier classifications.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_DEFAULT_WEIGHTS = {
    "demand": 0.35,
    "margin": 0.35,
    "competition": 0.30,
}


def build_composite(
    products: list[dict[str, Any]],
    demand_scores: list[dict[str, Any]],
    margin_scores: list[dict[str, Any]],
    competition_scores: list[dict[str, Any]],
    criteria: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build composite scores from individual dimension scores.

    Args:
        products: Original product list.
        demand_scores: Per-product demand scores.
        margin_scores: Per-product margin scores.
        competition_scores: Per-product competition scores.
        criteria: Optional weight overrides.

    Returns:
        Structured dict with scored products and distribution.
    """
    try:
        criteria = criteria or {}
        weights = {
            "demand": float(criteria.get("demand_weight", _DEFAULT_WEIGHTS["demand"])),
            "margin": float(criteria.get("margin_weight", _DEFAULT_WEIGHTS["margin"])),
            "competition": float(criteria.get("competition_weight", _DEFAULT_WEIGHTS["competition"])),
        }

        # Normalize weights
        total_w = sum(weights.values()) or 1.0
        weights = {k: v / total_w for k, v in weights.items()}

        demand_map = {str(s["id"]): s for s in demand_scores}
        margin_map = {str(s["id"]): s for s in margin_scores}
        comp_map = {str(s["id"]): s for s in competition_scores}

        scored: list[dict[str, Any]] = []
        distribution: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0}

        for product in copy.deepcopy(products):
            pid = str(product.get("id", "unknown"))
            d_score = demand_map.get(pid, {}).get("score", 0.0)
            m_score = margin_map.get(pid, {}).get("score", 0.0)
            c_score = comp_map.get(pid, {}).get("score", 0.0)

            composite = round(
                d_score * weights["demand"]
                + m_score * weights["margin"]
                + c_score * weights["competition"],
                2,
            )

            if composite >= 7.5:
                tier = "A"
            elif composite >= 5.0:
                tier = "B"
            elif composite >= 3.0:
                tier = "C"
            else:
                tier = "D"

            distribution[tier] = distribution.get(tier, 0) + 1

            scored.append({
                "id": pid,
                "title": str(product.get("title", "")),
                "composite_score": composite,
                "demand_score": d_score,
                "margin_score": m_score,
                "competition_score": c_score,
                "tier": tier,
            })

        scored.sort(key=lambda x: x["composite_score"], reverse=True)

        avg_score = round(
            sum(s["composite_score"] for s in scored) / max(len(scored), 1), 2
        )

        return {
            "status": "success",
            "scored_products": scored,
            "score_distribution": distribution,
            "avg_composite_score": avg_score,
        }
    except Exception as exc:
        return {"status": "error", "scored_products": [], "error": f"Composite build failed: {exc}"}
