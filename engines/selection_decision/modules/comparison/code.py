"""Product comparison engine — head-to-head analysis across all dimensions.

Main entry point: compare_products(input_payload)
Returns engine contract: {status, data, meta, error}

Produces:
  - Side-by-side comparison of top 2-5 products across all dimensions
  - Advantages / disadvantages per product
  - Trade-off analysis (margin vs demand, risk vs potential, etc.)
  - Winner per dimension (which product wins profitability? demand? risk?)
"""
from __future__ import annotations

import time
from typing import Any

from .data import get_dimension_weight, get_significance_level, get_tradeoff_template
from .logic import identify_tradeoffs, recommend_best_for_goal, create_comparison_matrix
from .rules import evaluate_comparison_rules


# Dimensions evaluated in comparisons
_DIMENSIONS = ["profitability", "demand", "competition", "risk", "trend"]


def compare_products(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Compare top products head-to-head across all scoring dimensions.

    Args:
        input_payload: {
            ranked_products: list[dict] — products sorted by unified_score,
                each containing normalized_scores dict
            goal: str — profit|growth|balanced
        }

    Returns:
        Engine contract: {status, data, meta, error}
    """
    start = time.time()

    try:
        ranked = input_payload.get("ranked_products", [])
        goal = input_payload.get("goal", "balanced")

        if not ranked or len(ranked) < 2:
            return _error("Need at least 2 ranked products to compare", start)

        # Cap at 5 products for comparison
        products = ranked[:5]

        # --- Build comparison matrix ---
        matrix = create_comparison_matrix(products)

        # --- Determine winner per dimension ---
        dimension_winners = _find_dimension_winners(products)

        # --- Identify advantages / disadvantages per product ---
        product_profiles = _build_product_profiles(products, dimension_winners, goal)

        # --- Trade-off analysis between top 2 ---
        tradeoffs = []
        for i in range(len(products)):
            for j in range(i + 1, len(products)):
                pair_tradeoffs = identify_tradeoffs(products[i], products[j])
                tradeoffs.extend(pair_tradeoffs)

        # --- Best product per goal ---
        best_for_goal = recommend_best_for_goal(products, goal)

        # --- Rules check ---
        rules_result = evaluate_comparison_rules({
            "product_count": len(products),
            "dimension_winners": dimension_winners,
            "products": products,
        })

        data = {
            "comparison_matrix": matrix,
            "dimension_winners": dimension_winners,
            "product_profiles": product_profiles,
            "tradeoffs": tradeoffs,
            "best_for_goal": best_for_goal,
            "rules": rules_result,
            "summary": _build_summary(dimension_winners, tradeoffs, products),
        }

        return {
            "status": "success",
            "data": data,
            "meta": {
                "module": "comparison",
                "duration_ms": round((time.time() - start) * 1000, 2),
                "products_compared": len(products),
                "goal": goal,
            },
            "error": None,
        }

    except (ValueError, KeyError, TypeError) as exc:
        return _error(str(exc), start)


def _find_dimension_winners(products: list[dict[str, Any]]) -> dict[str, Any]:
    """Determine which product wins each dimension."""
    winners: dict[str, Any] = {}

    for dim in _DIMENSIONS:
        best_pid = None
        best_score = -1.0
        second_score = -1.0

        for product in products:
            scores = product.get("normalized_scores", {})
            score = scores.get(dim)
            if score is None:
                continue
            if score > best_score:
                second_score = best_score
                best_score = score
                best_pid = product.get("product_id", "unknown")
            elif score > second_score:
                second_score = score

        gap = best_score - second_score if second_score >= 0 else 0
        significance = get_significance_level(gap)

        winners[dim] = {
            "winner_id": best_pid,
            "winner_score": round(best_score, 1),
            "runner_up_score": round(max(0, second_score), 1),
            "gap": round(gap, 1),
            "significance": significance["level"],
        }

    return winners


def _build_product_profiles(
    products: list[dict[str, Any]],
    dimension_winners: dict[str, Any],
    goal: str,
) -> list[dict[str, Any]]:
    """Build advantage/disadvantage profiles for each product."""
    profiles: list[dict[str, Any]] = []

    for product in products:
        pid = product.get("product_id", "unknown")
        scores = product.get("normalized_scores", {})
        advantages: list[str] = []
        disadvantages: list[str] = []
        dims_won = 0

        for dim in _DIMENSIONS:
            winner = dimension_winners.get(dim, {})
            score = scores.get(dim)
            weight = get_dimension_weight(goal, dim)

            if score is None:
                disadvantages.append(f"No data for {dim}")
                continue

            if winner.get("winner_id") == pid:
                dims_won += 1
                if winner["significance"] in ("decisive", "meaningful"):
                    advantages.append(
                        f"Wins {dim} by {winner['gap']:.0f} points ({winner['significance']})"
                    )
                else:
                    advantages.append(f"Leads in {dim} (marginal)")
            elif score < 30:
                disadvantages.append(f"Weak {dim} score ({score:.0f}/100)")
            elif score < 50:
                disadvantages.append(f"Below average {dim} ({score:.0f}/100)")

        profiles.append({
            "product_id": pid,
            "product_name": product.get("product_name", pid),
            "unified_score": product.get("unified_score", 0),
            "dimensions_won": dims_won,
            "advantages": advantages,
            "disadvantages": disadvantages,
            "critical_weaknesses": [d for d in disadvantages if "Weak" in d],
        })

    return profiles


def _build_summary(
    winners: dict[str, Any],
    tradeoffs: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a human-readable comparison summary."""
    # Count dimension wins per product
    win_counts: dict[str, int] = {}
    for dim_info in winners.values():
        wid = dim_info.get("winner_id")
        if wid:
            win_counts[wid] = win_counts.get(wid, 0) + 1

    dominant = max(win_counts, key=win_counts.get) if win_counts else None
    dominant_wins = win_counts.get(dominant, 0) if dominant else 0
    total_dims = len(_DIMENSIONS)
    has_majority = dominant_wins > total_dims / 2

    return {
        "dominant_product": dominant,
        "dimensions_won_by_dominant": dominant_wins,
        "has_majority": has_majority,
        "trade_off_count": len(tradeoffs),
        "verdict": (
            f"{dominant} wins {dominant_wins}/{total_dims} dimensions — clear leader"
            if has_majority
            else f"No clear winner. {dominant} leads with {dominant_wins}/{total_dims} dimensions"
        ),
    }


def _error(message: str, start: float) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {
            "module": "comparison",
            "duration_ms": round((time.time() - start) * 1000, 2),
        },
        "error": {"type": "ComparisonError", "message": message},
    }
