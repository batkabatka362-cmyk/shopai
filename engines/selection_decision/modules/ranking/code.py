"""Main product ranking engine.

Sorts products by unified score, assigns ranks, calculates score gaps,
groups into tiers, and flags too-close-to-call situations.
Returns the engine contract: {status, data, meta, error}.
"""

from __future__ import annotations

from typing import Any

from .data import (
    TIER_BOUNDARIES,
    SCORE_GAP_THRESHOLDS,
    MINIMUM_VIABLE_SCORE,
)
from .logic import (
    identify_clear_winner,
    assess_ranking_stability,
    recommend_shortlist_size,
)
from .rules import validate_ranking_inputs


def rank_products(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Rank products by their unified score and group into tiers.

    Args:
        input_payload: dict with keys:
            - products (list[dict]): each product dict must contain:
                - product_id (str): unique identifier
                - product_name (str): display name (optional)
                - unified_score (float): 0-100 aggregated score
                - risk_level (str): low|moderate|high|critical (optional)
                - profitability_positive (bool): margin > 0 (optional, default True)
                - confidence (dict): confidence assessment (optional)

    Returns:
        Engine contract dict {status, data, meta, error}.
    """
    try:
        products = input_payload.get("products")
        if not products or not isinstance(products, list):
            return _error("products list is required and must be non-empty")

        # --- Validate inputs against ranking rules ---
        validation = validate_ranking_inputs(products)
        if not validation["valid"] and validation.get("block"):
            return _error(
                f"Ranking blocked: {validation['violations'][0]['action']}"
            )

        # --- Filter out unqualified products ---
        qualified, disqualified = _partition_products(products)

        if not qualified:
            return _error(
                "No products meet minimum requirements for ranking "
                f"(min score {MINIMUM_VIABLE_SCORE}, positive profitability, risk not critical)"
            )

        # --- Sort by unified score descending ---
        ranked = sorted(qualified, key=lambda p: p["unified_score"], reverse=True)

        # --- Assign ranks and calculate gaps ---
        top_score = ranked[0]["unified_score"]
        ranked_results: list[dict[str, Any]] = []

        for i, product in enumerate(ranked):
            rank = i + 1
            score = product["unified_score"]

            # Gap to product above
            gap_to_above = round(ranked[i - 1]["unified_score"] - score, 1) if i > 0 else 0.0

            # Gap to top
            gap_to_top = round(top_score - score, 1)

            # Percentage of top score
            pct_of_top = round((score / top_score) * 100, 1) if top_score > 0 else 0.0

            # Assign tier
            tier = _assign_tier(score, top_score)

            ranked_results.append({
                "rank": rank,
                "product_id": product.get("product_id", "unknown"),
                "product_name": product.get("product_name", product.get("product_id", "unknown")),
                "unified_score": score,
                "tier": tier,
                "gap_to_above": gap_to_above,
                "gap_to_top": gap_to_top,
                "pct_of_top": pct_of_top,
                "confidence": product.get("confidence", {}),
            })

        # --- Identify too-close-to-call situations ---
        close_calls = _find_close_calls(ranked_results)

        # --- Identify clear winner ---
        winner_analysis = identify_clear_winner(ranked_results)

        # --- Assess ranking stability ---
        stability = assess_ranking_stability(ranked_results)

        # --- Recommend shortlist size ---
        shortlist = recommend_shortlist_size(ranked_results)

        # --- Build tier summary ---
        tier_summary = _build_tier_summary(ranked_results)

        return {
            "status": "success",
            "data": {
                "ranked_products": ranked_results,
                "disqualified_products": disqualified,
                "winner_analysis": winner_analysis,
                "stability": stability,
                "shortlist_recommendation": shortlist,
                "close_calls": close_calls,
                "tier_summary": tier_summary,
                "ranking_summary": {
                    "total_evaluated": len(products),
                    "total_qualified": len(qualified),
                    "total_disqualified": len(disqualified),
                    "top_score": top_score,
                    "bottom_score": ranked_results[-1]["unified_score"] if ranked_results else 0,
                    "score_spread": round(
                        top_score - ranked_results[-1]["unified_score"], 1
                    ) if ranked_results else 0,
                },
            },
            "meta": {
                "products_ranked": len(ranked_results),
                "products_disqualified": len(disqualified),
                "has_clear_winner": winner_analysis.get("has_clear_winner", False),
                "has_close_calls": len(close_calls) > 0,
            },
            "error": None,
        }

    except Exception as exc:
        return _error(f"Product ranking failed: {exc}")


def _partition_products(
    products: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split products into qualified and disqualified based on hard rules."""
    qualified: list[dict[str, Any]] = []
    disqualified: list[dict[str, Any]] = []

    for product in products:
        score = product.get("unified_score", 0)
        risk = product.get("risk_level", "moderate")
        profitable = product.get("profitability_positive", True)
        reasons: list[str] = []

        if score < MINIMUM_VIABLE_SCORE:
            reasons.append(f"Score {score} below minimum {MINIMUM_VIABLE_SCORE}")
        if not profitable:
            reasons.append("Profitability is not positive")
        if risk == "critical":
            reasons.append("Risk level is critical")

        if reasons:
            disqualified.append({
                "product_id": product.get("product_id", "unknown"),
                "product_name": product.get("product_name", "unknown"),
                "unified_score": score,
                "disqualification_reasons": reasons,
            })
        else:
            qualified.append(product)

    return qualified, disqualified


def _assign_tier(score: float, top_score: float) -> str:
    """Assign a tier based on proximity to the top score."""
    if top_score <= 0:
        return "bottom"
    pct_of_top = (score / top_score) * 100
    if pct_of_top >= TIER_BOUNDARIES["top_tier_pct"]:
        return "top"
    if pct_of_top >= TIER_BOUNDARIES["middle_tier_pct"]:
        return "middle"
    return "bottom"


def _find_close_calls(
    ranked: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find groups of products whose scores are too close to call."""
    close_calls: list[dict[str, Any]] = []
    threshold = SCORE_GAP_THRESHOLDS["too_close_to_call"]

    if len(ranked) < 2:
        return close_calls

    # Check consecutive pairs and groups
    group: list[dict[str, Any]] = [ranked[0]]
    for i in range(1, len(ranked)):
        gap = ranked[i - 1]["unified_score"] - ranked[i]["unified_score"]
        if gap <= threshold:
            group.append(ranked[i])
        else:
            if len(group) >= 2:
                close_calls.append({
                    "products": [p["product_id"] for p in group],
                    "ranks": [p["rank"] for p in group],
                    "score_range": (group[-1]["unified_score"], group[0]["unified_score"]),
                    "spread": round(group[0]["unified_score"] - group[-1]["unified_score"], 1),
                    "recommendation": "Scores too close to differentiate — gather more data or compare qualitatively",
                })
            group = [ranked[i]]

    # Handle final group
    if len(group) >= 2:
        close_calls.append({
            "products": [p["product_id"] for p in group],
            "ranks": [p["rank"] for p in group],
            "score_range": (group[-1]["unified_score"], group[0]["unified_score"]),
            "spread": round(group[0]["unified_score"] - group[-1]["unified_score"], 1),
            "recommendation": "Scores too close to differentiate — gather more data or compare qualitatively",
        })

    return close_calls


def _build_tier_summary(
    ranked: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build a summary of products per tier."""
    tiers: dict[str, list[str]] = {"top": [], "middle": [], "bottom": []}
    for product in ranked:
        tier = product.get("tier", "bottom")
        tiers.setdefault(tier, []).append(product["product_id"])

    return {
        tier: {
            "count": len(ids),
            "product_ids": ids,
        }
        for tier, ids in tiers.items()
    }


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {},
        "error": message,
    }
