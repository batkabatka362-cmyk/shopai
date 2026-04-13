"""Upsell Engine — timing optimizer.

Optimizes when and where to present each upsell offer. Different timings
have different conversion characteristics:

  - product_page: highest volume, moderate conversion, best for discovery
  - cart: high intent, good for "upgrade before you buy"
  - checkout: last chance, works for small price gaps only
  - post_purchase: no pressure, good for expensive upgrades
  - email_followup: delayed, works for considered purchases

Timing scores are derived from price gap psychology, conversion estimates,
and category norms — not random.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Timing profiles — base scores by timing type
# ---------------------------------------------------------------------------

_TIMING_PROFILES: dict[str, dict[str, float]] = {
    "product_page": {
        "base_score": 0.70,
        "small_gap_bonus": 0.10,     # works well for small upgrades
        "large_gap_bonus": 0.15,     # discovery context helps big upgrades
        "high_intent_bonus": 0.0,
        "low_pressure_bonus": 0.05,
    },
    "cart": {
        "base_score": 0.65,
        "small_gap_bonus": 0.20,     # "add $X for premium" works great
        "large_gap_bonus": -0.10,    # big price jump at cart = friction
        "high_intent_bonus": 0.15,
        "low_pressure_bonus": 0.0,
    },
    "checkout": {
        "base_score": 0.40,
        "small_gap_bonus": 0.30,     # "$5 more for premium" at checkout is powerful
        "large_gap_bonus": -0.25,    # never show expensive upgrades at checkout
        "high_intent_bonus": 0.20,
        "low_pressure_bonus": -0.10,
    },
    "post_purchase": {
        "base_score": 0.35,
        "small_gap_bonus": -0.05,    # small gap post-purchase feels like a missed deal
        "large_gap_bonus": 0.25,     # expensive upgrades work better here
        "high_intent_bonus": 0.05,
        "low_pressure_bonus": 0.20,
    },
    "email_followup": {
        "base_score": 0.30,
        "small_gap_bonus": 0.0,
        "large_gap_bonus": 0.20,     # time to consider expensive upgrades
        "high_intent_bonus": 0.0,
        "low_pressure_bonus": 0.25,
    },
}

# ---------------------------------------------------------------------------
# Category timing preferences
# ---------------------------------------------------------------------------

_CATEGORY_TIMING_BOOSTS: dict[str, dict[str, float]] = {
    "electronics": {"product_page": 0.10, "email_followup": 0.10},
    "software": {"cart": 0.10, "checkout": 0.10},
    "clothing": {"product_page": 0.15, "cart": 0.05},
    "food": {"cart": 0.15, "checkout": 0.10},
    "beauty": {"product_page": 0.10, "post_purchase": 0.10},
    "home": {"product_page": 0.05, "email_followup": 0.15},
    "sports": {"product_page": 0.10, "cart": 0.10},
}


def optimize_timing(
    candidates: list[dict[str, Any]],
    price_gaps: list[dict[str, Any]],
    conversion_estimates: list[dict[str, Any]],
    category: str = "general",
    customer_orders: int = 0,
) -> dict[str, Any]:
    """Optimize timing for all upsell candidates.

    Args:
        candidates: UpgradeCandidate list.
        price_gaps: PriceGapAnalysis list.
        conversion_estimates: ConversionEstimate list.
        category: Product category.
        customer_orders: Number of past orders (for intent signal).

    Returns:
        Structured dict with TimingRecommendation per candidate.
    """
    try:
        # Index by product_id
        gap_map: dict[str, dict[str, Any]] = {}
        for g in price_gaps:
            pid = str(g.get("product_id", ""))
            if pid:
                gap_map[pid] = g

        conv_map: dict[str, dict[str, Any]] = {}
        for c in conversion_estimates:
            pid = str(c.get("product_id", ""))
            if pid:
                conv_map[pid] = c

        recommendations: list[dict[str, Any]] = []

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            product_id = str(candidate.get("product_id", ""))
            gap = gap_map.get(product_id, {})
            conv = conv_map.get(product_id, {})

            rec = _optimize_single(
                product_id=product_id,
                gap=gap,
                conv=conv,
                category=category,
                customer_orders=customer_orders,
            )
            recommendations.append(rec)

        return {
            "status": "success",
            "recommendations": recommendations,
            "count": len(recommendations),
        }
    except Exception as exc:
        return {
            "status": "error",
            "recommendations": [],
            "error": f"Timing optimization failed: {exc}",
        }


def _optimize_single(
    product_id: str,
    gap: dict[str, Any],
    conv: dict[str, Any],
    category: str,
    customer_orders: int,
) -> dict[str, Any]:
    """Compute timing scores for one candidate."""

    pct_increase = float(gap.get("percentage_increase", 0.25))
    abs_diff = float(gap.get("absolute_difference", 20.0))
    psych_score = float(gap.get("psychological_score", 0.5))
    conversion_prob = float(conv.get("final_probability", 0.05))

    # Classify gap size
    is_small_gap = abs_diff < 15.0 or pct_increase < 0.15
    is_large_gap = abs_diff > 50.0 or pct_increase > 0.40

    # Intent signal from customer history
    is_high_intent = customer_orders >= 3

    # Compute score for each timing
    category_boosts = _CATEGORY_TIMING_BOOSTS.get(category.lower(), {})

    all_timings: list[dict[str, Any]] = []

    for timing_name, profile in _TIMING_PROFILES.items():
        score = profile["base_score"]

        if is_small_gap:
            score += profile["small_gap_bonus"]
        if is_large_gap:
            score += profile["large_gap_bonus"]
        if is_high_intent:
            score += profile["high_intent_bonus"]

        # Low pressure bonus for price-sensitive scenarios
        if psych_score < 0.4:
            score += profile["low_pressure_bonus"]

        # Category boost
        score += category_boosts.get(timing_name, 0.0)

        # Conversion probability boost (higher conversion = more aggressive timing)
        if conversion_prob > 0.12:
            # High conversion — push toward checkout/cart
            if timing_name in ("cart", "checkout"):
                score += 0.10

        score = max(0.0, min(1.0, score))
        all_timings.append({"timing": timing_name, "score": round(score, 4)})

    # Sort by score descending
    all_timings.sort(key=lambda t: t["score"], reverse=True)

    best_timing = all_timings[0]["timing"] if all_timings else "product_page"

    # Urgency level
    urgency = _determine_urgency(
        conversion_prob=conversion_prob,
        psych_score=psych_score,
        is_small_gap=is_small_gap,
    )

    # Rationale
    rationale = _build_rationale(
        best_timing=best_timing,
        is_small_gap=is_small_gap,
        is_large_gap=is_large_gap,
        conversion_prob=conversion_prob,
        category=category,
    )

    return {
        "product_id": product_id,
        "best_timing": best_timing,
        "all_timings": all_timings,
        "urgency_level": urgency,
        "rationale": rationale,
    }


def _determine_urgency(
    conversion_prob: float,
    psych_score: float,
    is_small_gap: bool,
) -> str:
    """Determine urgency level for the upsell presentation."""
    urgency_score = 0.0

    # High conversion = higher urgency to not miss the opportunity
    if conversion_prob > 0.15:
        urgency_score += 0.4
    elif conversion_prob > 0.08:
        urgency_score += 0.2

    # Good psychological fit = higher urgency
    if psych_score > 0.7:
        urgency_score += 0.3
    elif psych_score > 0.4:
        urgency_score += 0.15

    # Small gap = can be more aggressive
    if is_small_gap:
        urgency_score += 0.2

    if urgency_score >= 0.6:
        return "high"
    if urgency_score >= 0.3:
        return "medium"
    return "low"


def _build_rationale(
    best_timing: str,
    is_small_gap: bool,
    is_large_gap: bool,
    conversion_prob: float,
    category: str,
) -> str:
    """Build human-readable rationale for timing choice."""
    reasons: list[str] = []

    timing_reasons = {
        "product_page": "Product page gives discovery context for evaluation",
        "cart": "Cart timing leverages committed buying intent",
        "checkout": "Checkout timing works with the small price gap",
        "post_purchase": "Post-purchase removes time pressure for this upgrade",
        "email_followup": "Email follow-up allows considered evaluation",
    }
    reasons.append(timing_reasons.get(best_timing, "Best overall timing score"))

    if is_small_gap:
        reasons.append("Small price gap supports aggressive timing")
    elif is_large_gap:
        reasons.append("Large price gap favors low-pressure timing")

    if conversion_prob > 0.12:
        reasons.append(f"High estimated conversion ({conversion_prob:.0%}) supports prominent placement")

    return ". ".join(reasons)
