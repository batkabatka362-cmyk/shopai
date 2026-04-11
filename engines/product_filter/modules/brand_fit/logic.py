"""
logic.py — Brand positioning, dilution detection, and alternative suggestions.

Higher-order functions that use rules and data to provide strategic
brand guidance beyond simple scoring.
"""

from .rules import (
    QUALITY_TIERS,
    CATEGORY_AFFINITY,
    BRAND_COHERENCE_RULES,
    get_tier_distance,
    get_price_variance_limit,
)
from .data import BRAND_ARCHETYPES, get_archetype_profile


def _infer_price_tier(price):
    """Map a price to the most appropriate quality tier."""
    if price is None:
        return "mid_range"
    for tier, bounds in QUALITY_TIERS.items():
        if bounds["price_floor"] <= price <= bounds["price_ceiling"]:
            return tier
    return "luxury" if price > 500 else "budget"


def _catalog_price_stats(catalog):
    """Compute min, max, median price from a product catalog."""
    prices = [p.get("price", 0) for p in catalog if p.get("price") is not None]
    if not prices:
        return {"min": 0, "max": 0, "median": 0}
    prices.sort()
    mid = len(prices) // 2
    median = prices[mid] if len(prices) % 2 else (prices[mid - 1] + prices[mid]) / 2
    return {"min": prices[0], "max": prices[-1], "median": median}


def recommend_brand_positioning(products):
    """Analyze a set of products and recommend the best brand archetype.

    Parameters
    ----------
    products : list[dict]
        Products with price, category, rating, and tags/values.

    Returns
    -------
    dict  With keys: recommended_archetype, confidence, reasoning, alternatives.
    """
    if not products:
        return {"recommended_archetype": "value", "confidence": 0, "reasoning": "No products to analyze.", "alternatives": []}

    stats = _catalog_price_stats(products)
    avg_rating = sum(p.get("rating", 3.5) for p in products) / len(products)
    categories = list(set(p.get("category", "general") for p in products))
    all_tags = []
    for p in products:
        all_tags.extend(p.get("tags") or [])

    scores = {}
    for name, profile in BRAND_ARCHETYPES.items():
        score = 0
        tier = profile["price_tier"]
        tier_bounds = QUALITY_TIERS.get(tier, {})

        # Price alignment (0-30 points)
        if tier_bounds:
            if tier_bounds["price_floor"] <= stats["median"] <= tier_bounds["price_ceiling"]:
                score += 30
            elif abs(stats["median"] - (tier_bounds["price_floor"] + tier_bounds["price_ceiling"]) / 2) < 50:
                score += 15

        # Rating alignment (0-20 points)
        if avg_rating >= profile.get("min_rating", 3.0):
            score += 20
        elif avg_rating >= profile.get("min_rating", 3.0) - 0.5:
            score += 10

        # Category count alignment (0-20 points)
        max_cat = profile.get("max_categories", 5)
        if len(categories) <= max_cat:
            score += 20
        elif len(categories) <= max_cat + 2:
            score += 10

        # Value keyword overlap (0-30 points)
        profile_values = set(profile.get("values", []))
        tag_set = set(all_tags)
        overlap = len(profile_values & tag_set)
        score += min(30, overlap * 10)

        scores[name] = score

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    best_name, best_score = ranked[0]
    alternatives = [{"archetype": n, "score": s} for n, s in ranked[1:3]]

    return {
        "recommended_archetype": best_name,
        "confidence": min(100, best_score),
        "reasoning": f"Best match based on median price ${stats['median']:.0f}, "
                     f"avg rating {avg_rating:.1f}, {len(categories)} categories.",
        "alternatives": alternatives,
    }


def detect_brand_dilution(current_catalog, new_product):
    """Check whether adding a product would dilute the store's brand.

    Parameters
    ----------
    current_catalog : list[dict]
        Existing products in the store.
    new_product : dict
        The candidate product.

    Returns
    -------
    dict  With keys: dilution_risk (low/medium/high), reasons, score_impact.
    """
    if not current_catalog:
        return {"dilution_risk": "low", "reasons": [], "score_impact": 0}

    reasons = []
    stats = _catalog_price_stats(current_catalog)

    # Price variance check
    new_price = new_product.get("price", 0)
    if stats["median"] > 0 and new_price > 0:
        variance = max(new_price, stats["median"]) / max(min(new_price, stats["median"]), 0.01)
        if variance > BRAND_COHERENCE_RULES["max_price_variance_factor"]:
            reasons.append(
                f"Price ${new_price:.0f} is {variance:.1f}x the catalog median "
                f"${stats['median']:.0f} (max {BRAND_COHERENCE_RULES['max_price_variance_factor']}x)"
            )

    # Category sprawl check
    existing_cats = set(p.get("category", "") for p in current_catalog)
    new_cat = new_product.get("category", "")
    if new_cat and new_cat not in existing_cats:
        cat_count = len(existing_cats) + 1
        max_cats = BRAND_COHERENCE_RULES["max_categories"]
        if cat_count > max_cats:
            reasons.append(
                f"Adding category '{new_cat}' would make {cat_count} categories "
                f"(max recommended: {max_cats})"
            )

    # Quality tier distance check
    catalog_tier = _infer_price_tier(stats["median"])
    new_tier = _infer_price_tier(new_price)
    tier_dist = get_tier_distance(catalog_tier, new_tier)
    if tier_dist > BRAND_COHERENCE_RULES["quality_tier_adjacency_max"]:
        reasons.append(
            f"Quality tier '{new_tier}' is {tier_dist} steps from catalog tier "
            f"'{catalog_tier}' (max gap: {BRAND_COHERENCE_RULES['quality_tier_adjacency_max']})"
        )

    risk = "low" if len(reasons) == 0 else ("medium" if len(reasons) == 1 else "high")
    score_impact = -len(reasons) * 15

    return {
        "dilution_risk": risk,
        "reasons": reasons,
        "score_impact": score_impact,
    }


def suggest_brand_aligned_alternatives(rejected):
    """Suggest adjustments for rejected products to improve brand fit.

    Parameters
    ----------
    rejected : list[dict]
        Products that scored below the brand fit threshold.

    Returns
    -------
    list[dict]  Each with product reference, suggestion, and expected score boost.
    """
    suggestions = []
    for item in rejected:
        product = item.get("product", item)
        flags = item.get("flags", [])
        score = item.get("score", 0)

        product_suggestions = []
        if "price_coherence" in flags:
            product_suggestions.append({
                "issue": "Price out of brand range",
                "suggestion": "Find a variant in your brand's price tier or negotiate pricing",
                "expected_score_boost": 20,
            })
        if "category_coherence" in flags:
            product_suggestions.append({
                "issue": "Category does not fit store focus",
                "suggestion": "Consider a separate store or sub-brand for this category",
                "expected_score_boost": 15,
            })
        if "quality" in flags:
            product_suggestions.append({
                "issue": "Quality tier mismatch",
                "suggestion": "Source a higher/lower quality version matching your brand tier",
                "expected_score_boost": 20,
            })
        if "brand_values" in flags:
            product_suggestions.append({
                "issue": "Product values conflict with brand identity",
                "suggestion": "Check if the manufacturer offers a brand-aligned variant",
                "expected_score_boost": 15,
            })

        if not product_suggestions:
            product_suggestions.append({
                "issue": "General poor fit",
                "suggestion": "This product does not match your brand profile; skip it",
                "expected_score_boost": 0,
            })

        suggestions.append({
            "product_name": product.get("name", "unknown"),
            "current_score": score,
            "suggestions": product_suggestions,
        })

    return suggestions
