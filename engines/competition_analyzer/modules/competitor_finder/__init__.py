"""
Competitor Finder Module
========================
Identifies competitors selling similar products across marketplaces.
Analyzes competitive landscape, scores competitor strength, and classifies
competitors by threat level (direct, indirect, potential).
"""

from .code import find_competitors
from .logic import (
    assess_competitive_landscape,
    identify_vulnerable_competitors,
    estimate_market_share_distribution,
)
from .rules import (
    MIN_COMPETITORS_FOR_ANALYSIS,
    MAX_COMPETITORS_ANALYZED,
    PRICE_RANGE_TOLERANCE,
    DIRECT_COMPETITOR_CRITERIA,
    CONCENTRATION_THRESHOLDS,
    validate_competitor_data,
    is_direct_competitor,
    is_indirect_competitor,
)
from .data import (
    HHI_THRESHOLDS,
    STRENGTH_SCORING_WEIGHTS,
    STORE_AGE_BENCHMARKS,
    REVIEW_COUNT_THRESHOLDS,
    MARKET_CONCENTRATION_BENCHMARKS,
)
from .knowledge import (
    COMPETITIVE_INSIGHTS,
    COMPETITOR_DISCOVERY_SOURCES,
    MARKET_DIFFICULTY_RULES,
    get_market_difficulty_assessment,
    get_competitor_beatable_signals,
    get_discovery_strategy,
)

__all__ = [
    "find_competitors",
    "assess_competitive_landscape",
    "identify_vulnerable_competitors",
    "estimate_market_share_distribution",
    "MIN_COMPETITORS_FOR_ANALYSIS",
    "MAX_COMPETITORS_ANALYZED",
    "PRICE_RANGE_TOLERANCE",
    "DIRECT_COMPETITOR_CRITERIA",
    "CONCENTRATION_THRESHOLDS",
    "validate_competitor_data",
    "is_direct_competitor",
    "is_indirect_competitor",
    "HHI_THRESHOLDS",
    "STRENGTH_SCORING_WEIGHTS",
    "STORE_AGE_BENCHMARKS",
    "REVIEW_COUNT_THRESHOLDS",
    "MARKET_CONCENTRATION_BENCHMARKS",
    "COMPETITIVE_INSIGHTS",
    "COMPETITOR_DISCOVERY_SOURCES",
    "MARKET_DIFFICULTY_RULES",
    "get_market_difficulty_assessment",
    "get_competitor_beatable_signals",
    "get_discovery_strategy",
]

MODULE_NAME = "competitor_finder"
MODULE_VERSION = "1.0.0"
MODULE_DESCRIPTION = (
    "Identifies and analyzes competitors selling similar products, "
    "scoring their strength and classifying threat levels."
)

REQUIRED_INPUT_FIELDS = [
    "product_category",
    "price",
    "marketplace",
]

OPTIONAL_INPUT_FIELDS = [
    "keywords",
    "brand",
    "competitors_raw",
]

OUTPUT_FIELDS = [
    "competitors",
    "market_leaders",
    "total_competitor_count",
    "hhi_index",
    "landscape_assessment",
    "vulnerable_competitors",
    "market_share_distribution",
]
