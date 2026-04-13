"""
Price Comparison Module
=======================
Compares pricing across competitors to find positioning opportunities.
Analyzes price distributions, detects gaps and trends, evaluates your
position in the market, and calculates price-to-value ratios.
"""

from .code import compare_prices
from .logic import (
    recommend_price_position,
    detect_price_war,
    calculate_price_elasticity_estimate,
)
from .rules import (
    MAX_UNDERCUT_PERCENT,
    MIN_MARGIN_PERCENT,
    PREMIUM_MIN_RATING,
    CHARM_PRICE_CEILING,
    validate_price_input,
    check_margin_floor,
    is_premium_eligible,
)
from .data import (
    CATEGORY_PRICE_BENCHMARKS,
    TYPICAL_PRICE_RANGES,
    PRICE_REVIEW_CORRELATION,
    PRICE_WAR_INDICATORS,
    PERCENTILE_LABELS,
)
from .knowledge import (
    PRICING_PRINCIPLES,
    PRICING_PSYCHOLOGY_TACTICS,
    PRICE_POSITION_STRATEGIES,
    get_pricing_insight,
    get_charm_pricing_recommendation,
    get_competitive_pricing_guidance,
)

__all__ = [
    "compare_prices",
    "recommend_price_position",
    "detect_price_war",
    "calculate_price_elasticity_estimate",
    "MAX_UNDERCUT_PERCENT",
    "MIN_MARGIN_PERCENT",
    "PREMIUM_MIN_RATING",
    "CHARM_PRICE_CEILING",
    "validate_price_input",
    "check_margin_floor",
    "is_premium_eligible",
    "CATEGORY_PRICE_BENCHMARKS",
    "TYPICAL_PRICE_RANGES",
    "PRICE_REVIEW_CORRELATION",
    "PRICE_WAR_INDICATORS",
    "PERCENTILE_LABELS",
    "PRICING_PRINCIPLES",
    "PRICING_PSYCHOLOGY_TACTICS",
    "PRICE_POSITION_STRATEGIES",
    "get_pricing_insight",
    "get_charm_pricing_recommendation",
    "get_competitive_pricing_guidance",
]

MODULE_NAME = "price_comparison"
MODULE_VERSION = "1.0.0"
MODULE_DESCRIPTION = (
    "Compares pricing across competitors to find positioning opportunities, "
    "analyzing distributions, gaps, trends, and price-to-value ratios."
)

REQUIRED_INPUT_FIELDS = [
    "your_price",
    "competitor_prices",
    "product_category",
]

OPTIONAL_INPUT_FIELDS = [
    "your_rating",
    "your_review_count",
    "competitor_ratings",
    "competitor_review_counts",
    "cost_basis",
    "price_history",
]

OUTPUT_FIELDS = [
    "distribution",
    "price_gaps",
    "trends",
    "your_position",
    "price_to_value",
    "recommendation",
]
