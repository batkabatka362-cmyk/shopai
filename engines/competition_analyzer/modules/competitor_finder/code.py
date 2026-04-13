"""
Competitor Finder — Main Entry Point
Identifies competitors, scores strength, classifies threat level, computes HHI.
"""

from .rules import (
    MIN_COMPETITORS_FOR_ANALYSIS,
    MAX_COMPETITORS_ANALYZED,
    PRICE_RANGE_TOLERANCE,
    validate_competitor_data,
    is_direct_competitor,
    is_indirect_competitor,
)
from .data import STRENGTH_SCORING_WEIGHTS, HHI_THRESHOLDS
from .logic import (
    assess_competitive_landscape,
    identify_vulnerable_competitors,
    estimate_market_share_distribution,
)


def find_competitors(input_payload):
    """Engine contract function. Returns {status, data, meta, error}."""
    try:
        product_category = input_payload.get("product_category")
        price = input_payload.get("price")
        marketplace = input_payload.get("marketplace")
        keywords = input_payload.get("keywords", [])
        competitors_raw = input_payload.get("competitors_raw", [])

        if not product_category or price is None or not marketplace:
            return _error_response("Missing required fields: product_category, price, marketplace")

        if not competitors_raw:
            return _error_response("No competitor data provided in competitors_raw")

        validated = []
        for comp in competitors_raw[:MAX_COMPETITORS_ANALYZED]:
            if validate_competitor_data(comp):
                validated.append(comp)

        if len(validated) < MIN_COMPETITORS_FOR_ANALYSIS:
            return _error_response(
                f"Insufficient competitor data: found {len(validated)}, "
                f"need at least {MIN_COMPETITORS_FOR_ANALYSIS}"
            )

        scored = _score_all_competitors(validated)
        classified = _classify_competitors(scored, product_category, price, keywords)
        leaders = _detect_market_leaders(classified)
        hhi = _compute_hhi(classified)
        landscape = assess_competitive_landscape(classified)
        vulnerable = identify_vulnerable_competitors(classified)
        share_dist = estimate_market_share_distribution(classified)

        concentration_label = _label_concentration(hhi)

        data = {
            "competitors": classified, "market_leaders": leaders,
            "total_competitor_count": len(classified), "hhi_index": round(hhi, 2),
            "concentration_label": concentration_label, "landscape_assessment": landscape,
            "vulnerable_competitors": vulnerable, "market_share_distribution": share_dist,
        }
        meta = {
            "module": "competitor_finder", "version": "1.0.0",
            "competitors_analyzed": len(classified), "competitors_raw_received": len(competitors_raw),
            "marketplace": marketplace, "reference_price": price, "reference_category": product_category,
        }
        return {"status": "success", "data": data, "meta": meta, "error": None}
    except Exception as exc:
        return _error_response(f"Unexpected error: {str(exc)}")


def _error_response(message):
    return {
        "status": "error",
        "data": None,
        "meta": {"module": "competitor_finder", "version": "1.0.0"},
        "error": message,
    }


def _score_all_competitors(competitors):
    """Score each competitor's overall strength using weighted factors."""
    weights = STRENGTH_SCORING_WEIGHTS
    scored = []
    for comp in competitors:
        revenue = comp.get("estimated_revenue", 0)
        reviews = comp.get("review_count", 0)
        rating = comp.get("rating", 0)
        store_age_years = comp.get("store_age_years", 0)
        product_count = comp.get("product_count", 0)

        rev_score = min(revenue / 500000, 1.0) * weights["revenue"]
        review_score = min(reviews / 5000, 1.0) * weights["reviews"]
        rating_score = (rating / 5.0) * weights["rating"]
        age_score = min(store_age_years / 5.0, 1.0) * weights["store_age"]
        catalog_score = min(product_count / 200, 1.0) * weights["product_count"]

        total = rev_score + review_score + rating_score + age_score + catalog_score
        comp["strength_score"] = round(total, 4)
        scored.append(comp)

    scored.sort(key=lambda c: c["strength_score"], reverse=True)
    return scored


def _classify_competitors(competitors, category, price, keywords):
    """Classify each competitor as direct, indirect, or potential."""
    for comp in competitors:
        if is_direct_competitor(comp, category, price):
            comp["classification"] = "direct"
        elif is_indirect_competitor(comp, category, keywords):
            comp["classification"] = "indirect"
        else:
            comp["classification"] = "potential"
    return competitors


def _detect_market_leaders(competitors):
    """Return the top 3 competitors by strength score."""
    sorted_comps = sorted(competitors, key=lambda c: c.get("strength_score", 0), reverse=True)
    return [
        {k: c.get(k, "Unknown") for k in ("name", "strength_score", "estimated_revenue", "review_count", "classification")}
        for c in sorted_comps[:3]
    ]


def _compute_hhi(competitors):
    """Compute Herfindahl-Hirschman Index from estimated revenue shares."""
    total_revenue = sum(c.get("estimated_revenue", 0) for c in competitors)
    if total_revenue == 0:
        return 0.0
    return sum(((c.get("estimated_revenue", 0) / total_revenue) * 100) ** 2 for c in competitors)


def _label_concentration(hhi):
    """Return a human-readable label for the HHI value."""
    if hhi < HHI_THRESHOLDS["unconcentrated"]:
        return "unconcentrated"
    elif hhi < HHI_THRESHOLDS["moderate"]:
        return "moderately concentrated"
    else:
        return "highly concentrated"
