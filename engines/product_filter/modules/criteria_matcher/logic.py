"""
logic.py — Decision functions for criteria analysis and adjustment.

Provides recommendations on how to set or loosen filter criteria
based on the actual product distribution and rejection patterns.
"""

import statistics


def _safe_median(values):
    """Return the median of a numeric list, or None if empty."""
    cleaned = [v for v in values if v is not None]
    return statistics.median(cleaned) if cleaned else None


def _safe_percentile(values, pct):
    """Poor-man's percentile (no numpy dependency)."""
    cleaned = sorted(v for v in values if v is not None)
    if not cleaned:
        return None
    idx = int(len(cleaned) * pct / 100)
    idx = min(idx, len(cleaned) - 1)
    return cleaned[idx]


def recommend_criteria(products, goal=None):
    """Suggest optimal filter criteria based on product distribution.

    Examines the spread of margin, price, weight, rating, and reviews
    across the supplied products and picks thresholds that keep roughly
    the top 60-70 % (for *growth*) or top 30-40 % (for *profit*).

    Parameters
    ----------
    products : list[dict]
    goal : str | None  — "growth", "profit", or None (balanced)

    Returns
    -------
    dict  Suggested criteria values.
    """
    if not products:
        return {}

    margins = [p.get("margin_pct") for p in products]
    prices = [p.get("price") for p in products]
    weights = [p.get("weight_kg") for p in products]
    ratings = [p.get("rating") for p in products]
    reviews = [p.get("review_count") for p in products]

    if goal == "profit":
        margin_pct, price_lo, price_hi = 60, 30, 80
        weight_pct, rating_pct, review_pct = 40, 60, 60
    elif goal == "growth":
        margin_pct, price_lo, price_hi = 25, 10, 90
        weight_pct, rating_pct, review_pct = 80, 25, 25
    else:
        margin_pct, price_lo, price_hi = 40, 15, 85
        weight_pct, rating_pct, review_pct = 60, 40, 40

    suggested = {}

    margin_val = _safe_percentile(margins, margin_pct)
    if margin_val is not None:
        suggested["min_margin_pct"] = round(margin_val, 1)

    price_lo_val = _safe_percentile(prices, price_lo)
    price_hi_val = _safe_percentile(prices, price_hi)
    if price_lo_val is not None:
        suggested["min_price"] = round(price_lo_val, 2)
    if price_hi_val is not None:
        suggested["max_price"] = round(price_hi_val, 2)

    weight_val = _safe_percentile(weights, weight_pct)
    if weight_val is not None:
        suggested["max_weight_kg"] = round(weight_val, 2)

    rating_val = _safe_percentile(ratings, rating_pct)
    if rating_val is not None:
        suggested["min_rating"] = round(rating_val, 1)

    review_val = _safe_percentile(reviews, review_pct)
    if review_val is not None:
        suggested["min_review_count"] = int(review_val)

    suggested["_goal"] = goal or "balanced"
    return suggested


def analyze_rejection_patterns(rejected):
    """Identify the most common rejection reasons and suggest fixes.

    Parameters
    ----------
    rejected : list[dict]  — items from filter_by_criteria result

    Returns
    -------
    dict  {reason_tag: {count, pct, suggestion}}
    """
    if not rejected:
        return {"summary": "No rejections to analyze."}

    tag_counts = {}
    total = len(rejected)

    for item in rejected:
        seen_tags = set()
        for reason in item.get("rejection_reasons", []):
            tag = reason.split(" ")[0]
            if tag not in seen_tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
                seen_tags.add(tag)

    suggestions = {
        "margin": "Lower min_margin_pct or find higher-margin suppliers.",
        "price": "Widen the price range or review pricing strategy.",
        "weight": "Increase max_weight_kg or exclude heavy categories.",
        "category": "Add more categories to the allowed list.",
        "rating": "Lower min_rating or source better-reviewed products.",
        "review": "Lower min_review_count or allow newer products.",
    }

    analysis = {}
    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
        pct = round(count / total * 100, 1)
        analysis[tag] = {
            "count": count,
            "pct_of_rejected": pct,
            "suggestion": suggestions.get(tag, "Review this criterion."),
        }

    analysis["total_rejected"] = total
    return analysis


def adjust_criteria(current_criteria, rejection_rate):
    """If rejection rate is too high, return loosened criteria.

    Loosening strategy:
    - >80 % rejected  → aggressive loosening (30 % relaxation)
    - >60 % rejected  → moderate loosening (15 % relaxation)
    - <=60 % rejected → criteria are fine, return as-is

    Parameters
    ----------
    current_criteria : dict
    rejection_rate : float  (0.0 – 1.0)

    Returns
    -------
    dict  {adjusted_criteria, loosened, factor}
    """
    if rejection_rate <= 0.60:
        return {
            "adjusted_criteria": dict(current_criteria),
            "loosened": False,
            "factor": 1.0,
            "note": "Rejection rate acceptable; no adjustment needed.",
        }

    factor = 0.70 if rejection_rate > 0.80 else 0.85

    adjusted = dict(current_criteria)

    if "min_margin_pct" in adjusted:
        adjusted["min_margin_pct"] = round(adjusted["min_margin_pct"] * factor, 1)
    if "min_price" in adjusted:
        adjusted["min_price"] = round(adjusted["min_price"] * factor, 2)
    if "max_price" in adjusted:
        adjusted["max_price"] = round(adjusted["max_price"] / factor, 2)
    if "max_weight_kg" in adjusted:
        adjusted["max_weight_kg"] = round(adjusted["max_weight_kg"] / factor, 2)
    if "min_rating" in adjusted:
        new_rating = round(adjusted["min_rating"] * factor, 1)
        adjusted["min_rating"] = max(new_rating, 1.0)
    if "min_review_count" in adjusted:
        adjusted["min_review_count"] = max(int(adjusted["min_review_count"] * factor), 1)

    return {
        "adjusted_criteria": adjusted,
        "loosened": True,
        "factor": factor,
        "note": (
            f"Rejection rate {rejection_rate:.0%} is too high. "
            f"Criteria loosened by factor {factor}."
        ),
    }
