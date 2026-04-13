"""Cross-Sell Engine — affinity scorer.

Scores product affinity across four dimensions:
  1. Co-purchase rate — from association rules (support/confidence/lift)
  2. Category complement — how well the product's category fits the cart
  3. Price compatibility — whether the price is appropriate for a cross-sell
  4. Review correlation — proxy score based on category/price alignment

Model note: no model usage — deterministic scoring with weighted combination.
"""
from __future__ import annotations

import copy
import math
from typing import Any


# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "co_purchase": 0.35,
    "category_complement": 0.25,
    "price_compatibility": 0.25,
    "review_correlation": 0.15,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_affinity(
    complements: list[dict[str, Any]],
    associations: dict[str, Any],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Score each complement candidate on multi-dimensional affinity.

    Args:
        complements: List of ComplementMatch dicts from complement_matcher.
        associations: AssociationResult from association_finder.
        analysis: PurchaseAnalysis from purchase_analyzer.

    Returns:
        Structured dict with scored candidates and status.
    """
    try:
        safe_complements = copy.deepcopy(complements)
        safe_associations = copy.deepcopy(associations)
        safe_analysis = copy.deepcopy(analysis)

        rules = safe_associations.get("rules", [])
        category_prefs = safe_analysis.get("category_preferences", {})
        price_range = safe_analysis.get("price_range", {})
        cart_categories = safe_analysis.get("cart_categories", [])
        total_cart_value = safe_analysis.get("total_cart_value", 0)

        # Build rule lookup: consequent -> best rule metrics
        rule_index: dict[str, dict[str, float]] = {}
        for rule in rules:
            cid = rule.get("consequent", "")
            if not cid:
                continue
            existing = rule_index.get(cid)
            if existing is None or rule.get("lift", 0) > existing.get("lift", 0):
                rule_index[cid] = {
                    "support": float(rule.get("support", 0)),
                    "confidence": float(rule.get("confidence", 0)),
                    "lift": float(rule.get("lift", 0)),
                }

        scored: list[dict[str, Any]] = []
        for comp in safe_complements:
            pid = comp.get("product_id", "")
            prod_cat = str(comp.get("category", "")).lower()
            prod_price = float(comp.get("price", 0))

            # --- 1. Co-purchase score ---
            co_purchase_score = _score_co_purchase(pid, rule_index)

            # --- 2. Category complement score ---
            category_complement_score = _score_category_complement(
                prod_cat, cart_categories, category_prefs, comp.get("complement_type", "")
            )

            # --- 3. Price compatibility score ---
            price_compatibility_score = _score_price_compatibility(
                prod_price, price_range, total_cart_value
            )

            # --- 4. Review correlation score ---
            review_correlation_score = _score_review_correlation(
                prod_cat, cart_categories, category_prefs, prod_price, price_range
            )

            # --- Weighted total ---
            total_affinity = round(
                co_purchase_score * _WEIGHTS["co_purchase"]
                + category_complement_score * _WEIGHTS["category_complement"]
                + price_compatibility_score * _WEIGHTS["price_compatibility"]
                + review_correlation_score * _WEIGHTS["review_correlation"],
                4,
            )

            scored.append({
                "product_id": pid,
                "title": comp.get("title", ""),
                "category": comp.get("category", ""),
                "price": prod_price,
                "margin": float(comp.get("margin", 0)),
                "co_purchase_score": round(co_purchase_score, 4),
                "category_complement_score": round(category_complement_score, 4),
                "price_compatibility_score": round(price_compatibility_score, 4),
                "review_correlation_score": round(review_correlation_score, 4),
                "total_affinity": total_affinity,
                "complement_type": comp.get("complement_type", ""),
                "matched_cart_item": comp.get("matched_cart_item", ""),
            })

        # Sort by total affinity descending
        scored.sort(key=lambda s: s["total_affinity"], reverse=True)

        return {
            "status": "success",
            "scored_products": scored,
        }
    except Exception as exc:
        return {
            "status": "error",
            "scored_products": [],
            "error": f"Affinity scoring failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def _score_co_purchase(
    product_id: str,
    rule_index: dict[str, dict[str, float]],
) -> float:
    """Score based on association rule metrics (support, confidence, lift)."""
    metrics = rule_index.get(product_id)
    if metrics is None:
        return 0.1  # small baseline for unmatched products

    support = metrics.get("support", 0)
    confidence = metrics.get("confidence", 0)
    lift = metrics.get("lift", 0)

    # Combine: confidence is most predictive, lift indicates strength,
    # support indicates reliability
    score = (
        confidence * 0.5
        + min(lift / 5.0, 1.0) * 0.35  # cap lift contribution at 5x
        + support * 0.15
    )
    return min(max(score, 0.0), 1.0)


def _score_category_complement(
    product_category: str,
    cart_categories: list[str],
    category_preferences: dict[str, float],
    complement_type: str,
) -> float:
    """Score how well the product's category complements the cart."""
    score = 0.0

    # Different-category products score higher as cross-sells
    is_different = all(
        product_category != cc.lower() for cc in cart_categories
    )
    if is_different:
        score += 0.4
    else:
        score += 0.1  # same-category has lower cross-sell value

    # Bonus if category appears in customer preferences
    for cat, pref_score in category_preferences.items():
        if product_category in cat.lower() or cat.lower() in product_category:
            score += pref_score * 0.3
            break

    # Bonus by complement type
    type_bonuses = {
        "accessory": 0.3,
        "care_product": 0.25,
        "companion": 0.2,
        "upgrade": 0.15,
    }
    score += type_bonuses.get(complement_type, 0.1)

    return min(max(score, 0.0), 1.0)


def _score_price_compatibility(
    product_price: float,
    price_range: dict[str, float],
    total_cart_value: float,
) -> float:
    """Score price compatibility for cross-sell.

    Cross-sell items work best when priced lower than the main purchase.
    Sweet spot: 10-40% of cart average price.
    """
    avg_price = price_range.get("avg", 0)
    if avg_price <= 0 or product_price <= 0:
        return 0.3  # neutral score when data is missing

    ratio = product_price / avg_price

    # Ideal cross-sell price: 10-40% of the main item price
    if 0.1 <= ratio <= 0.4:
        score = 0.9
    elif 0.05 <= ratio <= 0.6:
        score = 0.7
    elif ratio <= 1.0:
        # Still acceptable up to same price
        score = max(0.3, 0.7 - (ratio - 0.6) * 0.8)
    else:
        # More expensive than cart average — poor cross-sell fit
        score = max(0.05, 0.3 - (ratio - 1.0) * 0.2)

    # Penalize if cross-sell would increase total by more than 50%
    if total_cart_value > 0:
        increase_ratio = product_price / total_cart_value
        if increase_ratio > 0.5:
            score *= 0.6

    return min(max(score, 0.0), 1.0)


def _score_review_correlation(
    product_category: str,
    cart_categories: list[str],
    category_preferences: dict[str, float],
    product_price: float,
    price_range: dict[str, float],
) -> float:
    """Proxy score for review correlation.

    Without actual review data, we estimate based on category affinity
    and price range alignment — products in preferred categories at
    typical price points tend to have correlated review patterns.
    """
    score = 0.3  # baseline

    # Category preference boost
    for cat, pref_score in category_preferences.items():
        if product_category in cat.lower() or cat.lower() in product_category:
            score += pref_score * 0.4
            break

    # Price-range alignment boost
    avg_price = price_range.get("avg", 0)
    if avg_price > 0 and product_price > 0:
        price_ratio = product_price / avg_price
        if 0.2 <= price_ratio <= 1.5:
            score += 0.2
        elif price_ratio <= 3.0:
            score += 0.1

    return min(max(score, 0.0), 1.0)
