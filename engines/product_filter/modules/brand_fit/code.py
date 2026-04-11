"""
code.py — Main brand fit evaluation entry point.

Accepts an input payload containing products and a brand profile,
scores each product 0-100 on brand alignment, and returns an
engine-contract response with accepted/rejected splits.
"""

from .rules import (
    QUALITY_TIERS,
    BRAND_COHERENCE_RULES,
    BRAND_VALUE_COMPATIBILITY,
    CATEGORY_AFFINITY,
    get_tier_distance,
)
from .data import BRAND_ARCHETYPES, get_archetype_profile, BRAND_VALUE_KEYWORDS
from .knowledge import diagnose_brand_issues


def _infer_tier(price):
    """Map a numeric price to a quality tier name."""
    if price is None:
        return "mid_range"
    for tier, bounds in QUALITY_TIERS.items():
        if bounds["price_floor"] <= price <= bounds["price_ceiling"]:
            return tier
    return "luxury" if price > 500 else "budget"


def _score_price_tier(product_price, brand_tier):
    """Score 0-25 based on how well the product price matches the brand tier."""
    product_tier = _infer_tier(product_price)
    distance = get_tier_distance(product_tier, brand_tier)
    if distance == 0:
        return 25
    elif distance == 1:
        return 15
    elif distance == 2:
        return 5
    return 0


def _score_category_coherence(product_category, brand_categories, archetype):
    """Score 0-25 based on category fit with the store's focus."""
    if not product_category:
        return 10
    cat = product_category.lower()

    # Direct match with declared brand categories
    if brand_categories and cat in [c.lower() for c in brand_categories]:
        return 25

    # Check affinity groups — product category is adjacent to a brand category
    for group_name, group_cats in CATEGORY_AFFINITY.items():
        lower_group = [c.lower() for c in group_cats]
        if cat in lower_group:
            for bc in (brand_categories or []):
                if bc.lower() in lower_group:
                    return 18
            break

    # No match at all
    if brand_categories and len(brand_categories) >= BRAND_COHERENCE_RULES["max_categories"]:
        return 0
    return 8


def _score_quality_match(product, brand_tier):
    """Score 0-20 based on rating and quality signals."""
    tier_spec = QUALITY_TIERS.get(brand_tier, QUALITY_TIERS["mid_range"])
    score = 0

    rating = product.get("rating")
    if rating is not None:
        if rating >= tier_spec["rating_min"]:
            score += 12
        elif rating >= tier_spec["rating_min"] - 0.5:
            score += 6

    review_count = product.get("review_count", 0)
    if review_count >= 100:
        score += 8
    elif review_count >= 20:
        score += 5
    elif review_count >= 5:
        score += 2

    return min(20, score)


def _score_demographic_fit(product, target_demographic):
    """Score 0-15 based on demographic alignment."""
    if not target_demographic:
        return 8

    product_demo = product.get("target_demographic", "").lower()
    if not product_demo:
        return 7  # neutral — no info

    if product_demo == target_demographic.lower():
        return 15

    # Adjacent demographics get partial credit
    adjacent_map = {
        "gen_z": ["millennial", "fitness"],
        "millennial": ["gen_z", "gen_x", "professional", "fitness"],
        "gen_x": ["millennial", "boomer", "professional", "parents"],
        "boomer": ["gen_x"],
        "parents": ["millennial", "gen_x"],
        "fitness": ["gen_z", "millennial"],
        "professional": ["millennial", "gen_x"],
    }
    adjacents = adjacent_map.get(target_demographic.lower(), [])
    if product_demo in adjacents:
        return 10

    return 3


def _score_brand_values(product, brand_values):
    """Score 0-15 based on alignment with brand values."""
    if not brand_values:
        return 8

    product_tags = set(t.lower() for t in (product.get("tags") or []))
    product_desc = (product.get("description") or "").lower()
    brand_vals = set(v.lower() for v in brand_values)

    score = 0
    matches = 0
    conflicts = 0

    # Check keyword matches
    for val in brand_vals:
        keywords = BRAND_VALUE_KEYWORDS.get(val, [])
        for kw in keywords:
            if kw in product_tags or kw in product_desc:
                matches += 1
                break

    # Check compatibility conflicts
    for val in brand_vals:
        compat = BRAND_VALUE_COMPATIBILITY.get(val, {})
        incompat = set(compat.get("incompatible", []))
        if product_tags & incompat:
            conflicts += 1

    score = min(15, matches * 5)
    score = max(0, score - conflicts * 8)
    return score


def _score_single_product(product, brand_profile, brand_categories, target_demographic):
    """Compute the full 0-100 brand fit score for one product."""
    brand_tier = brand_profile.get("price_tier", "mid_range")
    brand_values = brand_profile.get("values", [])

    price_score = _score_price_tier(product.get("price"), brand_tier)
    category_score = _score_category_coherence(
        product.get("category"), brand_categories, brand_profile
    )
    quality_score = _score_quality_match(product, brand_tier)
    demo_score = _score_demographic_fit(product, target_demographic)
    values_score = _score_brand_values(product, brand_values)

    total = price_score + category_score + quality_score + demo_score + values_score

    flags = []
    if price_score < 10:
        flags.append("price_coherence")
    if category_score < 10:
        flags.append("category_coherence")
    if quality_score < 8:
        flags.append("quality")
    if demo_score < 5:
        flags.append("targeting")
    if values_score < 5:
        flags.append("brand_values")

    return {
        "score": total,
        "breakdown": {
            "price_tier": price_score,
            "category_coherence": category_score,
            "quality_match": quality_score,
            "demographic_fit": demo_score,
            "brand_values": values_score,
        },
        "flags": flags,
    }


def check_brand_fit(input_payload):
    """Evaluate how well products fit the store's brand identity.

    Parameters
    ----------
    input_payload : dict
        - products           : list[dict]   — required
        - brand_archetype    : str           — e.g. "premium", "eco", "value"
        - brand_categories   : list[str]     — store's declared categories
        - target_demographic : str           — primary customer demographic
        - min_score          : int           — override rejection threshold (default 40)

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

        archetype = input_payload.get("brand_archetype", "value")
        brand_profile = get_archetype_profile(archetype)
        brand_categories = input_payload.get("brand_categories", [])
        target_demo = input_payload.get("target_demographic")
        min_score = input_payload.get("min_score", BRAND_COHERENCE_RULES["min_brand_fit_score"])

        accepted = []
        rejected = []

        for product in products:
            result = _score_single_product(product, brand_profile, brand_categories, target_demo)
            entry = {
                "product": product,
                "score": result["score"],
                "breakdown": result["breakdown"],
                "flags": result["flags"],
                "category": product.get("category", "unknown"),
            }
            if result["score"] >= min_score:
                accepted.append(entry)
            else:
                rejected.append(entry)

        total = len(products)
        all_results = accepted + rejected
        avg_score = sum(r["score"] for r in all_results) / total if total else 0
        diagnostics = diagnose_brand_issues(all_results, archetype)

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
                "rejection_rate": round(len(rejected) / total, 4) if total else 0.0,
                "average_brand_fit_score": round(avg_score, 1),
                "brand_archetype": archetype,
                "min_score_threshold": min_score,
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
