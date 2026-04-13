"""
code.py — Main filtering entry point.

Accepts an input payload containing products and optional criteria,
returns an engine-contract response with accepted/rejected splits.
"""

from .rules import DEFAULT_CRITERIA, get_criteria_for_goal
from .knowledge import diagnose_filter_results


def _check_product(product, criteria):
    """Check a single product against all supplied criteria.

    Returns a list of rejection reason strings.  An empty list means
    the product passed every applicable criterion.
    """
    reasons = []

    margin = product.get("margin_pct")
    if margin is not None and criteria.get("min_margin_pct") is not None:
        if margin < criteria["min_margin_pct"]:
            reasons.append(
                f"margin {margin:.1f}% below minimum {criteria['min_margin_pct']}%"
            )

    price = product.get("price")
    if price is not None:
        min_price = criteria.get("min_price")
        max_price = criteria.get("max_price")
        if min_price is not None and price < min_price:
            reasons.append(f"price ${price:.2f} below minimum ${min_price:.2f}")
        if max_price is not None and price > max_price:
            reasons.append(f"price ${price:.2f} above maximum ${max_price:.2f}")

    weight = product.get("weight_kg")
    if weight is not None and criteria.get("max_weight_kg") is not None:
        if weight > criteria["max_weight_kg"]:
            reasons.append(
                f"weight {weight}kg exceeds maximum {criteria['max_weight_kg']}kg"
            )

    category = product.get("category")
    allowed = criteria.get("allowed_categories")
    if category is not None and allowed is not None:
        if category.lower() not in [c.lower() for c in allowed]:
            reasons.append(f"category '{category}' not in allowed list")

    rating = product.get("rating")
    if rating is not None and criteria.get("min_rating") is not None:
        if rating < criteria["min_rating"]:
            reasons.append(
                f"rating {rating} below minimum {criteria['min_rating']}"
            )

    reviews = product.get("review_count")
    if reviews is not None and criteria.get("min_review_count") is not None:
        if reviews < criteria["min_review_count"]:
            reasons.append(
                f"review count {reviews} below minimum {criteria['min_review_count']}"
            )

    return reasons


def _build_rejection_breakdown(rejected_items):
    """Tally rejection reasons across all rejected products."""
    breakdown = {}
    for item in rejected_items:
        for reason in item["rejection_reasons"]:
            tag = reason.split(" ")[0]  # first word as bucket key
            breakdown[tag] = breakdown.get(tag, 0) + 1
    return breakdown


def filter_by_criteria(input_payload):
    """Filter products by business criteria.

    Parameters
    ----------
    input_payload : dict
        - products : list[dict]   — required
        - criteria : dict         — optional overrides (merged with defaults)
        - goal     : str|None     — "growth", "profit", or None

    Returns
    -------
    dict  Engine contract: {status, data, meta, error}
    """
    try:
        products = input_payload.get("products")
        if not products or not isinstance(products, list):
            return {
                "status": "error",
                "data": None,
                "meta": {},
                "error": "input_payload.products must be a non-empty list",
            }

        goal = input_payload.get("goal")
        base = get_criteria_for_goal(goal) if goal else dict(DEFAULT_CRITERIA)
        user_criteria = input_payload.get("criteria", {})
        criteria = {**base, **{k: v for k, v in user_criteria.items() if v is not None}}

        accepted = []
        rejected = []

        for product in products:
            reasons = _check_product(product, criteria)
            if reasons:
                rejected.append({
                    "product": product,
                    "rejection_reasons": reasons,
                })
            else:
                accepted.append(product)

        breakdown = _build_rejection_breakdown(rejected)
        total = len(products)
        rejection_rate = len(rejected) / total if total else 0.0
        diagnostics = diagnose_filter_results(rejection_rate, breakdown)

        return {
            "status": "success",
            "data": {
                "accepted": accepted,
                "rejected": rejected,
            },
            "meta": {
                "total_input": total,
                "accepted_count": len(accepted),
                "rejected_count": len(rejected),
                "rejection_rate": round(rejection_rate, 4),
                "rejection_breakdown": breakdown,
                "criteria_used": criteria,
                "diagnostics": diagnostics,
            },
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "error",
            "data": None,
            "meta": {},
            "error": str(exc),
        }
