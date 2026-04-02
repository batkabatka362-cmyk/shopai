"""Decision functions for product ranking.

Provides clear winner identification, ranking stability assessment,
and shortlist size recommendation for the final selection phase.
"""

from __future__ import annotations

from typing import Any

from .data import (
    SCORE_GAP_THRESHOLDS,
    RANKING_STABILITY_METRICS,
)


def identify_clear_winner(
    ranked: list[dict[str, Any]],
) -> dict[str, Any]:
    """Determine whether there is a dominant product choice.

    A clear winner exists when the top product's score exceeds the
    runner-up by a significant margin AND the top product has
    sufficiently high absolute score.

    Args:
        ranked: list of ranked product dicts (must be sorted by rank).

    Returns:
        Dict with winner analysis including has_clear_winner, winner details,
        and margin of victory.
    """
    if not ranked:
        return {
            "has_clear_winner": False,
            "reason": "No products to evaluate",
        }

    if len(ranked) == 1:
        product = ranked[0]
        return {
            "has_clear_winner": True,
            "winner": product["product_id"],
            "winner_score": product["unified_score"],
            "margin_of_victory": 0,
            "reason": "Only one qualified product",
            "confidence": "low — no comparison available",
        }

    top = ranked[0]
    runner_up = ranked[1]
    gap = round(top["unified_score"] - runner_up["unified_score"], 1)
    clear_gap = SCORE_GAP_THRESHOLDS["clear_winner"]

    if gap >= clear_gap and top["unified_score"] >= 55:
        return {
            "has_clear_winner": True,
            "winner": top["product_id"],
            "winner_score": top["unified_score"],
            "runner_up": runner_up["product_id"],
            "runner_up_score": runner_up["unified_score"],
            "margin_of_victory": gap,
            "reason": f"Score gap of {gap} points exceeds {clear_gap}-point threshold",
            "confidence": "high" if gap >= clear_gap * 1.5 else "moderate",
        }

    if gap < SCORE_GAP_THRESHOLDS["too_close_to_call"]:
        return {
            "has_clear_winner": False,
            "top_product": top["product_id"],
            "top_score": top["unified_score"],
            "runner_up": runner_up["product_id"],
            "runner_up_score": runner_up["unified_score"],
            "gap": gap,
            "reason": (
                f"Score gap of {gap} points is within the {SCORE_GAP_THRESHOLDS['too_close_to_call']}-point "
                f"too-close-to-call zone — need more data or qualitative comparison"
            ),
            "confidence": "low",
        }

    return {
        "has_clear_winner": False,
        "top_product": top["product_id"],
        "top_score": top["unified_score"],
        "runner_up": runner_up["product_id"],
        "runner_up_score": runner_up["unified_score"],
        "gap": gap,
        "reason": (
            f"Score gap of {gap} points is moderate — top product is leading "
            f"but not dominant enough for automatic selection"
        ),
        "confidence": "moderate",
    }


def assess_ranking_stability(
    ranked: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assess how stable the current ranking is to small score changes.

    Determines whether minor adjustments (within the margin of error)
    could flip the ranking order.

    Args:
        ranked: list of ranked product dicts sorted by rank.

    Returns:
        Dict with stability assessment.
    """
    if len(ranked) < 2:
        return {
            "stability": "n/a",
            "reason": "Need at least 2 products to assess stability",
            "vulnerable_positions": [],
        }

    margin_of_error = RANKING_STABILITY_METRICS["score_margin_of_error"]
    vulnerable: list[dict[str, Any]] = []

    for i in range(len(ranked) - 1):
        current = ranked[i]
        below = ranked[i + 1]
        gap = current["unified_score"] - below["unified_score"]

        if gap <= margin_of_error:
            vulnerable.append({
                "position": current["rank"],
                "product": current["product_id"],
                "score": current["unified_score"],
                "threatened_by": below["product_id"],
                "threatened_by_score": below["unified_score"],
                "gap": round(gap, 1),
                "note": f"Gap of {round(gap, 1)} is within +/-{margin_of_error} margin of error",
            })

    if not vulnerable:
        stability = "high"
        reason = "All ranking positions are separated by more than the margin of error"
    elif len(vulnerable) <= 1:
        stability = "moderate"
        reason = f"{len(vulnerable)} position(s) could flip with small score changes"
    else:
        stability = "low"
        reason = f"{len(vulnerable)} positions are vulnerable to minor score adjustments"

    return {
        "stability": stability,
        "margin_of_error": margin_of_error,
        "vulnerable_positions": vulnerable,
        "total_vulnerable": len(vulnerable),
        "reason": reason,
        "recommendation": (
            "Ranking is reliable — proceed with selection"
            if stability == "high"
            else "Consider gathering additional data to resolve close scores"
        ),
    }


def recommend_shortlist_size(
    ranked: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recommend how many products to keep for final human review.

    Uses score gaps and tier distribution to suggest an optimal shortlist
    that includes all competitive options without overwhelming the reviewer.

    Args:
        ranked: list of ranked product dicts sorted by rank.

    Returns:
        Dict with recommended shortlist size and reasoning.
    """
    if not ranked:
        return {"recommended_size": 0, "reason": "No products to shortlist"}

    total = len(ranked)
    if total <= 3:
        return {
            "recommended_size": total,
            "shortlisted_products": [p["product_id"] for p in ranked],
            "reason": f"Only {total} products — include all in final review",
        }

    # Find the natural break point: largest gap in the top portion
    max_gap = 0.0
    break_after = min(3, total)  # Default: top 3

    for i in range(min(total - 1, 7)):  # Check up to position 8
        gap = ranked[i]["unified_score"] - ranked[i + 1]["unified_score"]
        if gap > max_gap:
            max_gap = gap
            break_after = i + 1

    # Cap at 5 — more than 5 is analysis paralysis
    recommended = min(break_after, 5)

    # But ensure we include all top-tier products
    top_tier_count = sum(1 for p in ranked if p.get("tier") == "top")
    recommended = max(recommended, min(top_tier_count, 5))

    # Minimum 2 for comparison
    recommended = max(recommended, min(2, total))

    shortlisted = ranked[:recommended]

    return {
        "recommended_size": recommended,
        "shortlisted_products": [p["product_id"] for p in shortlisted],
        "natural_break_gap": round(max_gap, 1),
        "break_after_position": break_after,
        "top_tier_count": top_tier_count,
        "reason": (
            f"Natural score gap of {round(max_gap, 1)} points after position "
            f"{break_after} — shortlist top {recommended} for final review"
        ),
    }
