"""Comparison decision logic — trade-off identification, goal-based recommendation.

Analyzes pairs of products to find where they diverge, identifies meaningful
trade-offs, and recommends the best product for a specific business goal.
"""
from __future__ import annotations

from typing import Any

from .data import (
    DIMENSION_WEIGHTS,
    get_tradeoff_template,
    get_significance_level,
)


_DIMENSIONS = ["profitability", "demand", "competition", "risk", "trend"]


def identify_tradeoffs(
    product_a: dict[str, Any],
    product_b: dict[str, Any],
) -> list[dict[str, Any]]:
    """Identify trade-offs between two products.

    A trade-off exists when product A wins on dimension X but product B
    wins on dimension Y, and both gaps are significant.

    Args:
        product_a: Product dict with normalized_scores.
        product_b: Product dict with normalized_scores.

    Returns:
        List of trade-off dicts with dimensions, scores, and resolution hints.
    """
    scores_a = product_a.get("normalized_scores", {})
    scores_b = product_b.get("normalized_scores", {})
    pid_a = product_a.get("product_id", "A")
    pid_b = product_b.get("product_id", "B")

    # Find dimensions where each product wins
    a_wins: list[tuple[str, float]] = []
    b_wins: list[tuple[str, float]] = []

    for dim in _DIMENSIONS:
        sa = scores_a.get(dim)
        sb = scores_b.get(dim)
        if sa is None or sb is None:
            continue
        gap = sa - sb
        if gap > 5.0:
            a_wins.append((dim, gap))
        elif gap < -5.0:
            b_wins.append((dim, abs(gap)))

    # A trade-off exists when both products have meaningful wins
    tradeoffs: list[dict[str, Any]] = []
    for dim_a, gap_a in a_wins:
        for dim_b, gap_b in b_wins:
            template = get_tradeoff_template(dim_a, dim_b)
            threshold = template["threshold_gap"] if template else 15.0

            if gap_a >= threshold or gap_b >= threshold:
                tradeoffs.append({
                    "type": f"{dim_a}_vs_{dim_b}",
                    "product_a": {
                        "id": pid_a,
                        "wins_on": dim_a,
                        "score": scores_a.get(dim_a, 0),
                        "advantage": round(gap_a, 1),
                    },
                    "product_b": {
                        "id": pid_b,
                        "wins_on": dim_b,
                        "score": scores_b.get(dim_b, 0),
                        "advantage": round(gap_b, 1),
                    },
                    "description": template["description"] if template else (
                        f"{pid_a} wins on {dim_a} (+{gap_a:.0f}) but "
                        f"{pid_b} wins on {dim_b} (+{gap_b:.0f})"
                    ),
                    "resolution": template["resolution"] if template else (
                        "Evaluate based on your primary business goal."
                    ),
                })

    return tradeoffs


def recommend_best_for_goal(
    products: list[dict[str, Any]],
    goal: str,
) -> dict[str, Any]:
    """Recommend the best product for a specific business goal.

    Re-scores products using goal-specific dimension weights.

    Args:
        products: List of product dicts with normalized_scores.
        goal: 'profit', 'growth', or 'balanced'.

    Returns:
        {best_product_id, goal, weighted_scores, explanation}
    """
    weights = DIMENSION_WEIGHTS.get(goal, DIMENSION_WEIGHTS["balanced"])
    scored: list[dict[str, Any]] = []

    for product in products:
        pid = product.get("product_id", "unknown")
        scores = product.get("normalized_scores", {})

        weighted_total = 0.0
        weight_sum = 0.0
        breakdown: dict[str, float] = {}

        for dim, weight in weights.items():
            score = scores.get(dim)
            if score is not None:
                weighted_total += score * weight
                weight_sum += weight
                breakdown[dim] = round(score * weight, 1)

        # Normalize if some dimensions are missing
        final_score = (weighted_total / weight_sum * 100) if weight_sum > 0 else 0
        final_score = round(min(100.0, final_score), 1)

        scored.append({
            "product_id": pid,
            "goal_score": final_score,
            "breakdown": breakdown,
        })

    scored.sort(key=lambda s: s["goal_score"], reverse=True)
    best = scored[0] if scored else None

    if not best:
        return {"best_product_id": None, "goal": goal, "explanation": "No products to evaluate"}

    runner_up = scored[1] if len(scored) > 1 else None
    gap = best["goal_score"] - runner_up["goal_score"] if runner_up else 100.0

    return {
        "best_product_id": best["product_id"],
        "goal": goal,
        "goal_score": best["goal_score"],
        "breakdown": best["breakdown"],
        "runner_up_id": runner_up["product_id"] if runner_up else None,
        "runner_up_score": runner_up["goal_score"] if runner_up else None,
        "gap": round(gap, 1),
        "explanation": (
            f"For {goal} goal, {best['product_id']} scores {best['goal_score']:.0f} "
            f"(vs {runner_up['goal_score']:.0f} for {runner_up['product_id']})"
            if runner_up
            else f"For {goal} goal, {best['product_id']} scores {best['goal_score']:.0f}"
        ),
    }


def create_comparison_matrix(
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create a dimension-by-product comparison matrix.

    Args:
        products: List of product dicts with normalized_scores.

    Returns:
        List of rows, one per dimension, with all product scores and winner.
    """
    matrix: list[dict[str, Any]] = []

    for dim in _DIMENSIONS:
        row_scores: dict[str, float | None] = {}
        best_pid = None
        best_score = -1.0

        for product in products:
            pid = product.get("product_id", "unknown")
            score = product.get("normalized_scores", {}).get(dim)
            row_scores[pid] = score
            if score is not None and score > best_score:
                best_score = score
                best_pid = pid

        # Calculate gap between top 2
        sorted_scores = sorted(
            [s for s in row_scores.values() if s is not None],
            reverse=True,
        )
        gap = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) >= 2 else 0
        significance = get_significance_level(gap)

        matrix.append({
            "dimension": dim,
            "scores": row_scores,
            "winner": best_pid,
            "winner_score": round(best_score, 1) if best_score >= 0 else None,
            "gap": round(gap, 1),
            "significance": significance["level"],
        })

    return matrix
