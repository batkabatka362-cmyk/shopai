"""Market trends detection — identify growing, declining, and emerging categories.

Analyzes multiple signals to determine market direction:
  - Search volume trends (Google Trends proxy)
  - Social media mentions velocity
  - Marketplace bestseller movement
  - Year-over-year category growth
  - New product launch frequency

Trend score: -100 (dying) to +100 (exploding)
"""
from __future__ import annotations

import math
from typing import Any

from utils.helpers import safe_float, safe_int


# Trend velocity thresholds
TREND_LEVELS = {
    "exploding": {"min_score": 80, "label": "Rapidly growing — act fast"},
    "growing": {"min_score": 40, "label": "Steady growth — good time to enter"},
    "stable": {"min_score": -10, "label": "Flat — established market, harder to break in"},
    "declining": {"min_score": -40, "label": "Shrinking — avoid unless you have unique angle"},
    "dying": {"min_score": -100, "label": "Collapsing — do not enter"},
}


def compute_trend_score(signals: dict[str, Any]) -> dict[str, Any]:
    """Compute a composite trend score from multiple signals.

    Args:
        signals: {
            "search_growth_pct": float,      # YoY search volume change (-100 to +500)
            "social_mentions_growth": float,  # YoY social mentions change
            "marketplace_rank_change": float, # Rank improvement (positive = better)
            "new_products_launched": int,     # New products in category last 90 days
            "review_volume_growth": float,    # YoY review volume change
            "price_trend_pct": float,         # Average price change (rising = demand > supply)
        }

    Returns:
        Composite trend score with breakdown.
    """
    weights = {
        "search_growth": 0.30,
        "social_growth": 0.20,
        "marketplace_movement": 0.15,
        "new_product_activity": 0.15,
        "review_activity": 0.10,
        "price_signal": 0.10,
    }

    components = {}

    # Search growth (strongest signal)
    search_growth = safe_float(signals.get("search_growth_pct", 0))
    search_score = _normalize_growth(search_growth, cap=200)
    components["search_growth"] = {
        "raw": search_growth,
        "score": search_score,
        "weight": weights["search_growth"],
        "interpretation": _interpret_growth(search_growth, "Search volume"),
    }

    # Social mentions growth
    social_growth = safe_float(signals.get("social_mentions_growth", 0))
    social_score = _normalize_growth(social_growth, cap=300)
    components["social_growth"] = {
        "raw": social_growth,
        "score": social_score,
        "weight": weights["social_growth"],
        "interpretation": _interpret_growth(social_growth, "Social mentions"),
    }

    # Marketplace rank change (positive = moving up bestseller lists)
    rank_change = safe_float(signals.get("marketplace_rank_change", 0))
    rank_score = min(100, max(-100, rank_change * 2))
    components["marketplace_movement"] = {
        "raw": rank_change,
        "score": rank_score,
        "weight": weights["marketplace_movement"],
        "interpretation": f"Rank {'improved' if rank_change > 0 else 'declined'} by {abs(rank_change):.0f} positions",
    }

    # New product launch activity (high = market is active)
    new_products = safe_int(signals.get("new_products_launched", 0))
    product_score = min(100, new_products * 2) if new_products > 0 else -20
    components["new_product_activity"] = {
        "raw": new_products,
        "score": product_score,
        "weight": weights["new_product_activity"],
        "interpretation": f"{new_products} new products launched — {'active' if new_products > 10 else 'quiet'} market",
    }

    # Review volume growth (people are buying and reviewing)
    review_growth = safe_float(signals.get("review_volume_growth", 0))
    review_score = _normalize_growth(review_growth, cap=150)
    components["review_activity"] = {
        "raw": review_growth,
        "score": review_score,
        "weight": weights["review_activity"],
        "interpretation": _interpret_growth(review_growth, "Review volume"),
    }

    # Price trend (rising prices = demand > supply = opportunity)
    price_trend = safe_float(signals.get("price_trend_pct", 0))
    price_score = min(100, max(-100, price_trend * 5))
    components["price_signal"] = {
        "raw": price_trend,
        "score": price_score,
        "weight": weights["price_signal"],
        "interpretation": f"Prices {'rising' if price_trend > 0 else 'falling'} {abs(price_trend):.1f}% — {'demand > supply' if price_trend > 0 else 'supply > demand'}",
    }

    # Weighted composite
    composite = sum(
        components[key]["score"] * components[key]["weight"]
        for key in components
    )
    composite = round(max(-100, min(100, composite)), 1)

    # Determine trend level
    trend_level = "dying"
    for level, config in TREND_LEVELS.items():
        if composite >= config["min_score"]:
            trend_level = level
            break

    return {
        "trend_score": composite,
        "trend_level": trend_level,
        "trend_label": TREND_LEVELS[trend_level]["label"],
        "components": components,
        "signal_count": sum(1 for v in signals.values() if v is not None and v != 0),
        "confidence": _signal_confidence(signals),
    }


def analyze_category_trends(
    categories: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze trends across multiple categories and rank them.

    Args:
        categories: List of {
            "name": str,
            "signals": {search_growth_pct, social_mentions_growth, ...}
        }
    """
    results = []
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        name = cat.get("name", "Unknown")
        signals = cat.get("signals", {})
        trend = compute_trend_score(signals)
        results.append({
            "category": name,
            **trend,
        })

    results.sort(key=lambda r: r["trend_score"], reverse=True)

    return {
        "categories_analyzed": len(results),
        "ranked": results,
        "top_growing": [r for r in results if r["trend_level"] in ("exploding", "growing")][:5],
        "declining": [r for r in results if r["trend_level"] in ("declining", "dying")],
    }


def detect_momentum_shift(
    current_signals: dict[str, Any],
    previous_signals: dict[str, Any],
) -> dict[str, Any]:
    """Detect if a category's trend is accelerating or decelerating.

    Compares two time periods to find momentum changes.
    """
    current = compute_trend_score(current_signals)
    previous = compute_trend_score(previous_signals)

    delta = current["trend_score"] - previous["trend_score"]

    if delta > 20:
        momentum = "accelerating"
        interpretation = "Trend is getting STRONGER — opportunity window opening"
    elif delta > 5:
        momentum = "improving"
        interpretation = "Slight improvement in trend"
    elif delta > -5:
        momentum = "steady"
        interpretation = "No significant change in trend direction"
    elif delta > -20:
        momentum = "slowing"
        interpretation = "Trend is weakening — watch closely"
    else:
        momentum = "reversing"
        interpretation = "Trend is REVERSING — reassess strategy"

    return {
        "current_score": current["trend_score"],
        "previous_score": previous["trend_score"],
        "delta": round(delta, 1),
        "momentum": momentum,
        "interpretation": interpretation,
        "current_level": current["trend_level"],
        "previous_level": previous["trend_level"],
        "level_changed": current["trend_level"] != previous["trend_level"],
    }


def _normalize_growth(growth_pct: float, cap: float = 200) -> float:
    """Normalize growth % to -100..+100 score using log curve."""
    if growth_pct >= 0:
        return min(100, math.log1p(growth_pct) / math.log1p(cap) * 100)
    else:
        return max(-100, -math.log1p(abs(growth_pct)) / math.log1p(100) * 100)


def _interpret_growth(pct: float, label: str) -> str:
    """Human-readable interpretation of growth percentage."""
    if pct > 100:
        return f"{label} exploding (+{pct:.0f}%)"
    if pct > 30:
        return f"{label} growing strongly (+{pct:.0f}%)"
    if pct > 5:
        return f"{label} growing moderately (+{pct:.0f}%)"
    if pct > -5:
        return f"{label} flat ({pct:+.0f}%)"
    if pct > -30:
        return f"{label} declining ({pct:.0f}%)"
    return f"{label} collapsing ({pct:.0f}%)"


def _signal_confidence(signals: dict[str, Any]) -> str:
    """How confident are we in the trend based on signal count?"""
    non_zero = sum(1 for v in signals.values() if v is not None and v != 0)
    if non_zero >= 5:
        return "high"
    if non_zero >= 3:
        return "medium"
    if non_zero >= 1:
        return "low"
    return "none"
