"""Conversion data — benchmarks, rates, and reference tables.

Sources: industry reports (Littledata, Shopify, Statista, Baymard Institute).
All rates are expressed as decimals (0.025 = 2.5%).
"""
from __future__ import annotations

import time
from typing import Any


# Average conversion rates by product category (e-commerce)
CATEGORY_CONVERSION_RATES = {
    "electronics": 0.018,
    "clothing": 0.030,
    "home_garden": 0.025,
    "health_beauty": 0.035,
    "sports_outdoors": 0.022,
    "toys_games": 0.028,
    "pet_supplies": 0.032,
    "office_supplies": 0.040,
    "automotive": 0.015,
    "food_beverage": 0.038,
    "baby": 0.033,
    "jewelry": 0.012,
    "books": 0.045,
    "arts_crafts": 0.035,
    "luxury": 0.008,
    "general": 0.025,
}

# Traffic source conversion multipliers (relative to baseline)
TRAFFIC_SOURCE_MULTIPLIERS = {
    "paid_social": 0.70,       # Cold, interruptive — lowest intent
    "paid_search": 1.20,       # High intent — actively searching
    "organic_search": 1.30,    # High intent + trust signal (SEO)
    "organic_social": 0.80,    # Moderate intent — discovery
    "email": 2.50,             # Warm/hot — known audience
    "direct": 1.80,            # Returning visitors — brand familiarity
    "referral": 1.50,          # Trust via third-party endorsement
    "affiliate": 1.10,         # Pre-qualified traffic
    "influencer": 0.90,        # Discovery but with social proof
}

# Price point impact on conversion (higher price = more friction)
PRICE_POINT_MODIFIERS = [
    {"max_price": 10, "modifier": 1.40, "label": "impulse_buy"},
    {"max_price": 25, "modifier": 1.20, "label": "low_consideration"},
    {"max_price": 50, "modifier": 1.00, "label": "moderate"},
    {"max_price": 100, "modifier": 0.80, "label": "considered_purchase"},
    {"max_price": 200, "modifier": 0.60, "label": "high_consideration"},
    {"max_price": 500, "modifier": 0.40, "label": "major_purchase"},
    {"max_price": float("inf"), "modifier": 0.25, "label": "luxury_purchase"},
]

# Review count impact on conversion
REVIEW_IMPACT = {
    "count_brackets": [
        {"max_reviews": 0, "modifier": 0.60, "label": "no_reviews"},
        {"max_reviews": 5, "modifier": 0.80, "label": "few_reviews"},
        {"max_reviews": 10, "modifier": 1.00, "label": "credible"},
        {"max_reviews": 50, "modifier": 1.20, "label": "established"},
        {"max_reviews": 200, "modifier": 1.35, "label": "popular"},
        {"max_reviews": float("inf"), "modifier": 1.45, "label": "highly_trusted"},
    ],
}

# Funnel stage benchmarks (what % pass through each stage)
FUNNEL_STAGE_BENCHMARKS = {
    "impression_to_click": 0.035,     # 3.5% CTR
    "click_to_visit": 0.85,          # 85% of clicks land successfully
    "visit_to_cart": 0.08,           # 8% add to cart
    "cart_to_checkout": 0.30,        # 30% proceed to checkout (70% abandon)
    "checkout_to_purchase": 0.55,    # 55% complete purchase
}

# Cart abandonment reasons and their frequency
CART_ABANDONMENT_REASONS = {
    "extra_costs_too_high": 0.48,     # Shipping, tax, fees
    "account_creation_required": 0.24,
    "too_slow_delivery": 0.22,
    "too_long_checkout": 0.18,
    "didnt_trust_site": 0.17,
    "couldnt_see_total_cost": 0.16,
    "returns_policy_unsatisfactory": 0.12,
    "website_errors": 0.11,
    "not_enough_payment_methods": 0.09,
    "card_declined": 0.04,
}


class ConversionRecord:
    """A single conversion estimation record."""

    def __init__(
        self,
        category: str,
        conversion_rate: float,
        daily_visitors: int,
        daily_purchases: float,
        traffic_source: str = "mixed",
        timestamp: float | None = None,
    ) -> None:
        self.category = category
        self.conversion_rate = conversion_rate
        self.daily_visitors = daily_visitors
        self.daily_purchases = daily_purchases
        self.traffic_source = traffic_source
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "conversion_rate": self.conversion_rate,
            "daily_visitors": self.daily_visitors,
            "daily_purchases": self.daily_purchases,
            "traffic_source": self.traffic_source,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversionRecord:
        return cls(
            category=data["category"],
            conversion_rate=data["conversion_rate"],
            daily_visitors=data["daily_visitors"],
            daily_purchases=data["daily_purchases"],
            traffic_source=data.get("traffic_source", "mixed"),
            timestamp=data.get("timestamp"),
        )


def get_category_conversion(category: str) -> float:
    """Get benchmark conversion rate for a category."""
    return CATEGORY_CONVERSION_RATES.get(category, 0.025)


def get_source_conversion(source: str) -> float:
    """Get conversion multiplier for a traffic source."""
    return TRAFFIC_SOURCE_MULTIPLIERS.get(source, 1.0)


def get_abandonment_rate(device: str = "global_average") -> float:
    """Get cart abandonment rate benchmark."""
    from .rules import CART_ABANDONMENT_BENCHMARKS
    return CART_ABANDONMENT_BENCHMARKS.get(device, 0.70)
