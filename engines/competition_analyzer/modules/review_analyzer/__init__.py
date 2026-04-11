"""
review_analyzer — Analyze competitor reviews to find weaknesses and opportunities.

Examines rating distributions, sentiment, complaint patterns, and review
authenticity to surface actionable product and marketing insights.
"""

from .code import analyze_reviews
from .logic import (
    extract_product_opportunities,
    assess_review_moat,
    recommend_review_strategy,
)
from .rules import (
    MIN_REVIEWS_FOR_ANALYSIS,
    MAX_REVIEW_AGE_YEARS,
    HIGH_NEGATIVE_THRESHOLD,
    validate_review_dataset,
    check_review_authenticity,
    flag_suspicious_patterns,
)
from .data import (
    CATEGORY_BENCHMARKS,
    VELOCITY_BENCHMARKS,
    COMPLAINT_KEYWORDS,
    FAKE_REVIEW_INDICATORS,
    get_benchmark_for_category,
    get_complaint_category,
)
from .knowledge import (
    REVIEW_INSIGHTS,
    get_insight,
    get_insights_for_stage,
    get_all_actionable_tips,
)

__all__ = [
    # Core entry point
    "analyze_reviews",
    # Logic helpers
    "extract_product_opportunities",
    "assess_review_moat",
    "recommend_review_strategy",
    # Rules and validation
    "MIN_REVIEWS_FOR_ANALYSIS",
    "MAX_REVIEW_AGE_YEARS",
    "HIGH_NEGATIVE_THRESHOLD",
    "validate_review_dataset",
    "check_review_authenticity",
    "flag_suspicious_patterns",
    # Benchmark data
    "CATEGORY_BENCHMARKS",
    "VELOCITY_BENCHMARKS",
    "COMPLAINT_KEYWORDS",
    "FAKE_REVIEW_INDICATORS",
    "get_benchmark_for_category",
    "get_complaint_category",
    # Knowledge base
    "REVIEW_INSIGHTS",
    "get_insight",
    "get_insights_for_stage",
    "get_all_actionable_tips",
]

MODULE_NAME = "review_analyzer"
MODULE_VERSION = "1.0.0"
MODULE_DESCRIPTION = (
    "Analyzes competitor reviews to extract weaknesses, opportunities, "
    "and actionable strategies for building a stronger review profile."
)

ENGINE = "competition_analyzer"
CATEGORY = "reviews"

CAPABILITIES = [
    "rating_distribution_analysis",
    "review_velocity_tracking",
    "sentiment_breakdown",
    "complaint_extraction",
    "praise_extraction",
    "review_quality_comparison",
    "fake_review_detection",
    "product_opportunity_mapping",
    "review_moat_assessment",
    "review_strategy_recommendation",
]
