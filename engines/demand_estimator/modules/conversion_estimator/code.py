"""Conversion estimation — how many visitors become buyers.

Models the full e-commerce conversion funnel:
  impression → click → visit → add-to-cart → checkout → purchase

Key factors affecting conversion:
  - Product category (electronics converts differently from fashion)
  - Price point (higher price = more consideration = lower conversion)
  - Review count & rating (social proof drives trust)
  - Traffic source (cold ads vs warm email vs organic)
  - Landing page quality (speed, design, UX)
"""
from __future__ import annotations

from typing import Any

from .data import (
    CATEGORY_CONVERSION_RATES,
    TRAFFIC_SOURCE_MULTIPLIERS,
    PRICE_POINT_MODIFIERS,
    FUNNEL_STAGE_BENCHMARKS,
    REVIEW_IMPACT,
)


def estimate_conversion(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Estimate conversion rate and purchase volume for a product/store.

    Args:
        input_payload: {
            "category": str,
            "price": float,
            "review_count": int,
            "avg_rating": float,           # 1.0 - 5.0
            "traffic_source": str,         # "paid_social", "paid_search", "organic", "email", "direct"
            "landing_page_quality": float,  # 0.0 - 1.0 (1.0 = best)
            "daily_visitors": int,
        }

    Returns:
        Estimated conversion rate, funnel breakdown, daily/monthly purchases.
    """
    category = input_payload.get("category", "general")
    price = input_payload.get("price", 30.0)
    review_count = input_payload.get("review_count", 0)
    avg_rating = input_payload.get("avg_rating", 0.0)
    traffic_source = input_payload.get("traffic_source", "paid_social")
    lp_quality = input_payload.get("landing_page_quality", 0.5)
    daily_visitors = input_payload.get("daily_visitors", 100)

    # Base conversion rate from category
    base_rate = _get_base_rate(category)

    # Apply modifiers
    price_mod = _price_modifier(price)
    review_mod = _review_modifier(review_count, avg_rating)
    source_mod = TRAFFIC_SOURCE_MULTIPLIERS.get(traffic_source, 1.0)
    lp_mod = 0.5 + (lp_quality * 1.0)  # 0.5x to 1.5x

    adjusted_rate = base_rate * price_mod * review_mod * source_mod * lp_mod
    adjusted_rate = max(0.002, min(0.25, adjusted_rate))  # Clamp to realistic bounds

    funnel = estimate_funnel_throughput(daily_visitors, adjusted_rate)
    daily_purchases = funnel["purchases"]
    monthly_purchases = round(daily_purchases * 30, 1)

    return {
        "conversion_rate": round(adjusted_rate * 100, 2),
        "daily_purchases": daily_purchases,
        "monthly_purchases": monthly_purchases,
        "monthly_revenue": round(monthly_purchases * price, 2),
        "funnel": funnel,
        "modifiers": {
            "base_rate": round(base_rate * 100, 2),
            "price_modifier": round(price_mod, 3),
            "review_modifier": round(review_mod, 3),
            "source_modifier": round(source_mod, 3),
            "landing_page_modifier": round(lp_mod, 3),
        },
        "input": input_payload,
    }


def estimate_funnel_throughput(
    daily_visitors: int, overall_conversion: float
) -> dict[str, Any]:
    """Break down the full funnel from visitors to purchases.

    Distributes the overall conversion rate across funnel stages using
    benchmark drop-off ratios.
    """
    stages = FUNNEL_STAGE_BENCHMARKS
    stage_names = ["impression_to_click", "click_to_visit", "visit_to_cart",
                   "cart_to_checkout", "checkout_to_purchase"]

    # Benchmark total pass-through from the stage rates
    benchmark_passthrough = 1.0
    for name in stage_names:
        benchmark_passthrough *= stages[name]

    # Scale factor to adjust stages proportionally to match our overall rate
    if benchmark_passthrough > 0:
        scale = (overall_conversion / benchmark_passthrough) ** (1 / len(stage_names))
    else:
        scale = 1.0

    funnel_result = {"visitors": daily_visitors}
    current = float(daily_visitors)

    for name in stage_names:
        stage_rate = min(0.95, stages[name] * scale)
        current = current * stage_rate
        funnel_result[name] = round(stage_rate * 100, 1)

    funnel_result["purchases"] = round(current, 1)
    return funnel_result


def estimate_daily_purchases(
    daily_visitors: int, conversion_rate: float, price: float
) -> dict[str, Any]:
    """Quick estimate of daily purchases and revenue."""
    purchases = daily_visitors * conversion_rate
    return {
        "daily_purchases": round(purchases, 1),
        "monthly_purchases": round(purchases * 30, 1),
        "daily_revenue": round(purchases * price, 2),
        "monthly_revenue": round(purchases * 30 * price, 2),
    }


def _get_base_rate(category: str) -> float:
    """Look up base conversion rate for a category."""
    cat = category.lower().replace(" ", "_").replace("-", "_")
    if cat in CATEGORY_CONVERSION_RATES:
        return CATEGORY_CONVERSION_RATES[cat]
    for key in CATEGORY_CONVERSION_RATES:
        if key in cat or cat in key:
            return CATEGORY_CONVERSION_RATES[key]
    return 0.025  # Default 2.5%


def _price_modifier(price: float) -> float:
    """Higher prices reduce conversion. Returns multiplier."""
    for bracket in PRICE_POINT_MODIFIERS:
        if price <= bracket["max_price"]:
            return bracket["modifier"]
    return PRICE_POINT_MODIFIERS[-1]["modifier"]


def _review_modifier(review_count: int, avg_rating: float) -> float:
    """More reviews and higher rating boost conversion."""
    # Review count impact
    count_mod = 1.0
    for bracket in REVIEW_IMPACT["count_brackets"]:
        if review_count <= bracket["max_reviews"]:
            count_mod = bracket["modifier"]
            break
    else:
        count_mod = REVIEW_IMPACT["count_brackets"][-1]["modifier"]

    # Rating impact
    if avg_rating >= 4.5:
        rating_mod = 1.15
    elif avg_rating >= 4.0:
        rating_mod = 1.05
    elif avg_rating >= 3.5:
        rating_mod = 0.95
    elif avg_rating >= 3.0:
        rating_mod = 0.80
    elif avg_rating > 0:
        rating_mod = 0.50
    else:
        rating_mod = 0.85  # No rating = slight penalty

    return count_mod * rating_mod
