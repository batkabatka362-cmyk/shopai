"""Cross-Sell Engine — recommendation ranker.

Ranks cross-sell recommendations by expected_revenue * conversion_probability
and applies diversity rules to avoid showing too many items from the same
category.

Model note: LLaMA — ranking optimization and reason generation.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MAX_RECOMMENDATIONS = 8
_MAX_PER_CATEGORY = 3
_DIVERSITY_PENALTY = 0.15  # penalty per duplicate category item


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rank_recommendations(
    scored_products: list[dict[str, Any]],
    estimates: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Rank cross-sell recommendations for final output.

    Combines affinity scores with revenue estimates, applies diversity
    rules, and generates human-readable reasons.

    Args:
        scored_products: AffinityScore list from affinity_scorer.
        estimates: RevenueEstimate list from revenue_estimator.
        analysis: PurchaseAnalysis from purchase_analyzer.

    Returns:
        Structured dict with ranked recommendations and status.
    """
    try:
        safe_products = copy.deepcopy(scored_products)
        safe_estimates = copy.deepcopy(estimates)
        safe_analysis = copy.deepcopy(analysis)

        # Build estimate lookup by product_id
        estimate_index: dict[str, dict[str, Any]] = {}
        for est in safe_estimates:
            pid = est.get("product_id", "")
            if pid:
                estimate_index[pid] = est

        # Merge affinity scores with revenue estimates
        candidates: list[dict[str, Any]] = []
        for product in safe_products:
            pid = product.get("product_id", "")
            est = estimate_index.get(pid, {})

            affinity = float(product.get("total_affinity", 0))
            conversion = float(est.get("conversion_probability", 0))
            expected_revenue = float(est.get("expected_revenue", 0))

            # Composite ranking score: revenue * conversion weighted by affinity
            rank_score = (
                expected_revenue * 0.4
                + conversion * affinity * 100 * 0.35
                + affinity * 100 * 0.25
            )

            candidates.append({
                "product_id": pid,
                "title": product.get("title", ""),
                "category": product.get("category", ""),
                "price": float(product.get("price", 0)),
                "affinity": affinity,
                "conversion": conversion,
                "expected_revenue": expected_revenue,
                "complement_type": product.get("complement_type", ""),
                "matched_cart_item": product.get("matched_cart_item", ""),
                "factors": est.get("factors", []),
                "rank_score": round(rank_score, 4),
            })

        # Sort by rank_score descending
        candidates.sort(key=lambda c: c["rank_score"], reverse=True)

        # Apply diversity rules
        ranked = _apply_diversity(candidates)

        # Generate final recommendations with reasons
        recommendations: list[dict[str, Any]] = []
        for i, cand in enumerate(ranked[:_MAX_RECOMMENDATIONS]):
            reason = _generate_reason(cand, safe_analysis)
            recommendations.append({
                "product_id": cand["product_id"],
                "title": cand["title"],
                "reason": reason,
                "score": round(cand["rank_score"], 4),
                "expected_revenue": cand["expected_revenue"],
                "model_note": f"LLaMA: ranked #{i + 1} by composite score (affinity={cand['affinity']:.2f}, conversion={cand['conversion']:.2f})",
            })

        return {
            "status": "success",
            "recommendations": recommendations,
        }
    except Exception as exc:
        return {
            "status": "error",
            "recommendations": [],
            "error": f"Recommendation ranking failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply_diversity(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply diversity rules to avoid category saturation.

    Penalizes candidates if their category already has too many selections,
    then re-sorts.
    """
    category_counts: dict[str, int] = {}
    diversified: list[dict[str, Any]] = []

    for cand in candidates:
        cat = str(cand.get("category", "")).lower()
        count = category_counts.get(cat, 0)

        if count >= _MAX_PER_CATEGORY:
            continue  # skip entirely if category is saturated

        # Apply penalty for duplicate categories
        if count > 0:
            cand["rank_score"] = max(
                0,
                cand["rank_score"] - _DIVERSITY_PENALTY * count * cand["rank_score"],
            )

        category_counts[cat] = count + 1
        diversified.append(cand)

    # Re-sort after penalties
    diversified.sort(key=lambda c: c["rank_score"], reverse=True)
    return diversified


def _generate_reason(
    candidate: dict[str, Any],
    analysis: dict[str, Any],
) -> str:
    """Generate a human-readable reason for the recommendation."""
    complement_type = candidate.get("complement_type", "companion")
    title = candidate.get("title", "this product")
    category = candidate.get("category", "")
    cart_categories = analysis.get("cart_categories", [])
    factors = candidate.get("factors", [])

    # Build reason from complement type and context
    type_phrases = {
        "accessory": f"Recommended accessory for your {', '.join(cart_categories)} purchase",
        "care_product": f"Care product to maintain your {', '.join(cart_categories)} items",
        "companion": f"Complements your cart — popular with similar shoppers",
        "upgrade": f"Enhancement for your {', '.join(cart_categories)} selection",
    }

    reason = type_phrases.get(complement_type, "Recommended based on your cart")

    # Add a factor-based detail if available
    if factors:
        detail = factors[0]
        if detail not in reason:
            reason = f"{reason}. {detail}"

    return reason
