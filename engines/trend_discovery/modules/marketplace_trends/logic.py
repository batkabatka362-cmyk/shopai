"""Marketplace trends decision logic — which bestseller products to pursue.

Not every bestseller is a viable product opportunity. This decides:
  - Should we enter this marketplace niche or stay away?
  - Is this bestseller a durable trend or a flash sale fluke?
  - What adjacent products can ride the same demand wave?
"""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_float, safe_int


def decide_marketplace_entry(trend_data: dict[str, Any]) -> dict[str, Any]:
    """Should we enter this marketplace niche? Returns enter/monitor/skip."""
    bsr_velocity = trend_data.get("bsr_velocity", 0)
    cross_mkt = trend_data.get("cross_marketplace_score", 0)
    composite = trend_data.get("composite_score", 0)
    review_count = safe_int(trend_data.get("review_count", 0))
    price = safe_float(trend_data.get("price", 0))
    rating = safe_float(trend_data.get("rating", 0))

    entry_score = composite

    # Cross-marketplace confirmation is the strongest signal
    if cross_mkt >= 60:
        entry_score += 15
        cross_note = "Strong cross-marketplace demand — high confidence entry signal"
    elif cross_mkt >= 30:
        entry_score += 5
        cross_note = "Some cross-marketplace presence — moderate confirmation"
    elif cross_mkt > 0:
        cross_note = "Weak cross-marketplace signal — needs further validation"
    else:
        entry_score -= 10
        cross_note = "Single marketplace only — demand may be platform-specific"

    # Review moat assessment — high review count = hard to compete
    if review_count >= 5000:
        entry_score -= 20
        review_note = "Heavy review moat (5000+) — extremely difficult to compete on reviews"
    elif review_count >= 1000:
        entry_score -= 10
        review_note = "Moderate review moat (1000+) — need differentiation to compete"
    elif review_count >= 100:
        review_note = "Low review moat — competitive entry still possible"
    else:
        entry_score += 10
        review_note = "Minimal reviews — early market, good entry window"

    # Price point viability
    if 15 <= price <= 50:
        entry_score += 10
        price_note = "Sweet spot price ($15-$50) — best margin-to-volume ratio"
    elif 50 < price <= 100:
        entry_score += 5
        price_note = "Mid-range price ($50-$100) — decent margins if differentiated"
    elif price > 100:
        price_note = "High price point ($100+) — needs strong brand trust"
    elif price > 0:
        entry_score -= 5
        price_note = "Low price (under $15) — thin margins, hard to profit with ads"
    else:
        price_note = "Price unknown — cannot assess margin viability"

    # Rating gap opportunity
    if 0 < rating < 4.0:
        entry_score += 10
        rating_note = "Low category rating — opportunity to win on quality"
    elif rating >= 4.5:
        entry_score -= 5
        rating_note = "High category rating — incumbents have strong quality"
    else:
        rating_note = f"Average category rating ({rating}) — compete on features"

    entry_score = max(0, min(100, entry_score))

    if entry_score >= 70:
        verdict = "enter"
        action = "Market entry viable — source product, validate margins, prepare listing"
    elif entry_score >= 40:
        verdict = "monitor"
        action = "Promising but uncertain — track BSR for 7-14 days before committing"
    else:
        verdict = "skip"
        action = "Not viable for entry — too competitive or insufficient demand signal"

    return {
        "verdict": verdict,
        "entry_score": entry_score,
        "action": action,
        "factors": {
            "cross_marketplace": cross_note,
            "review_moat": review_note,
            "price_viability": price_note,
            "rating_gap": rating_note,
        },
    }


def assess_bestseller_durability(signals: dict[str, Any]) -> dict[str, Any]:
    """Is this bestseller rank durable or a temporary spike?

    Signals used:
      - bsr_age_days: how long the product has held strong BSR
      - bsr_consistency: how stable the rank has been (vs wild swings)
      - review_velocity: are reviews still growing?
      - seasonal_match: does the product align with current season?
      - promotion_driven: is the rank from a flash sale / coupon?
    """
    age_days = safe_int(signals.get("bsr_age_days", 0))
    consistency = safe_float(signals.get("bsr_consistency", 0.5))
    review_velocity = safe_float(signals.get("review_velocity", 0))
    seasonal = signals.get("seasonal_match", False)
    promo_driven = signals.get("promotion_driven", False)

    durability = 50  # baseline

    # BSR age assessment
    if age_days < 3:
        durability -= 20
        age_note = "BSR spike < 3 days — could be a flash sale or single viral event"
    elif 3 <= age_days <= 14:
        durability += 10
        age_note = "BSR held 3-14 days — showing real sustained demand"
    elif 14 < age_days <= 60:
        durability += 20
        age_note = "BSR sustained 2-8 weeks — strong durability signal"
    else:
        durability += 15
        age_note = "BSR stable 60+ days — established product, check for declining velocity"

    # Rank consistency (0.0 = wild swings, 1.0 = rock solid)
    if consistency >= 0.7:
        durability += 15
        consistency_note = "Very stable BSR — consistent daily sales volume"
    elif consistency >= 0.4:
        durability += 5
        consistency_note = "Moderate BSR fluctuation — normal demand variance"
    else:
        durability -= 15
        consistency_note = "Erratic BSR — demand is unpredictable, risky to stock"

    # Review velocity — growing reviews = growing market
    if review_velocity >= 5:
        durability += 10
        review_note = "Strong review growth — market is actively expanding"
    elif review_velocity >= 1:
        durability += 5
        review_note = "Steady review growth — healthy demand"
    else:
        review_note = "Slow review growth — market may be plateauing"

    # Seasonal adjustment
    if seasonal:
        durability -= 10
        seasonal_note = "Seasonal product — demand will drop after season ends"
    else:
        durability += 5
        seasonal_note = "Non-seasonal / evergreen product — year-round demand"

    # Promotion-driven rank is misleading
    if promo_driven:
        durability -= 25
        promo_note = "BSR appears promotion-driven — rank will likely drop when deal ends"
    else:
        promo_note = "No promotion detected — organic rank"

    durability = max(0, min(100, durability))

    if durability >= 70:
        outlook = "durable"
        window = "3-12 months of viable sales if you enter now"
    elif durability >= 40:
        outlook = "moderate"
        window = "1-3 months — enter quickly or the window may close"
    else:
        outlook = "fragile"
        window = "Under 1 month — only pursue if you can ship very fast"

    return {
        "outlook": outlook,
        "durability_score": durability,
        "estimated_window": window,
        "factors": {
            "age": age_note,
            "consistency": consistency_note,
            "review_velocity": review_note,
            "seasonal": seasonal_note,
            "promotion": promo_note,
        },
    }


def find_adjacent_opportunities(bestseller: dict[str, Any]) -> dict[str, Any]:
    """Find adjacent product opportunities near a confirmed bestseller.

    Instead of copying the bestseller (IP risk, review moat), find products
    that ride the same demand wave: accessories, bundles, variations.

    bestseller: dict with name, category, price, features, target_audience
    """
    name = bestseller.get("name", "")
    category = bestseller.get("category", "")
    price = safe_float(bestseller.get("price", 0))
    features = bestseller.get("features", [])
    audience = bestseller.get("target_audience", "")

    opportunities: list[dict[str, Any]] = []

    # 1. Accessory play — products that complement the bestseller
    opportunities.append({
        "type": "accessory",
        "strategy": f"Create accessories or add-ons for '{name}'",
        "price_range": f"${max(5, price * 0.15):.0f}-${price * 0.40:.0f}",
        "margin_potential": "high",
        "competition_level": "low-medium",
        "rationale": "Bestseller buyers actively search for compatible accessories",
        "risk": "Low — no direct competition with the bestseller itself",
    })

    # 2. Bundle play — combine bestseller category with complementary item
    opportunities.append({
        "type": "bundle",
        "strategy": f"Bundle a '{category}' product with complementary items",
        "price_range": f"${price * 1.2:.0f}-${price * 1.8:.0f}",
        "margin_potential": "medium-high",
        "competition_level": "low",
        "rationale": "Bundles differentiate from single-product listings and increase AOV",
        "risk": "Medium — need to validate bundle demand before large inventory",
    })

    # 3. Premium variation — higher quality version at higher price
    opportunities.append({
        "type": "premium_variation",
        "strategy": f"Offer premium version of '{category}' products with better materials/features",
        "price_range": f"${price * 1.5:.0f}-${price * 2.5:.0f}",
        "margin_potential": "high",
        "competition_level": "medium",
        "rationale": "If bestseller has < 4.5 stars, quality gap exists in the market",
        "risk": "Medium — higher upfront cost, need to validate willingness to pay premium",
    })

    # 4. Budget alternative — capture price-sensitive segment
    if price >= 25:
        opportunities.append({
            "type": "budget_alternative",
            "strategy": f"Offer a budget-friendly alternative in '{category}'",
            "price_range": f"${price * 0.4:.0f}-${price * 0.65:.0f}",
            "margin_potential": "medium",
            "competition_level": "medium-high",
            "rationale": "Many shoppers search for cheaper alternatives to bestsellers",
            "risk": "Medium — race to bottom on price, need efficient sourcing",
        })

    # 5. Adjacent audience — same audience, different need
    if audience:
        opportunities.append({
            "type": "adjacent_audience",
            "strategy": f"Target '{audience}' audience with related product in nearby category",
            "price_range": f"${price * 0.7:.0f}-${price * 1.3:.0f}",
            "margin_potential": "medium",
            "competition_level": "low-medium",
            "rationale": "Same buyer persona often purchases across related categories",
            "risk": "Low-medium — audience validated, product-market fit needs testing",
        })

    return {
        "bestseller_reference": name,
        "category": category,
        "adjacent_opportunities": opportunities,
        "recommended_approach": _pick_best_adjacent(opportunities, price),
    }


def _pick_best_adjacent(opportunities: list[dict[str, Any]], price: float) -> str:
    """Pick the best adjacent strategy based on available opportunities."""
    if price >= 50:
        return "Start with accessories (low risk, high margin), then test a premium variation"
    elif price >= 20:
        return "Lead with a bundle play (differentiation + higher AOV), add accessories"
    else:
        return "Focus on bundles or premium variation — accessory margins too thin at this price"
