"""
Market Position Module
======================
Determines optimal market positioning by mapping the competitive landscape
on a price-vs-quality matrix, identifying empty positions, recommending
positioning archetypes, and scoring positioning fit.
"""

from .code import analyze_market_position
from .logic import (
    recommend_positioning,
    detect_positioning_conflicts,
    estimate_repositioning_effort,
)
from .rules import (
    RULES,
    evaluate_rules,
    POSITION_CONSISTENCY_REQUIRED,
    MARGIN_FLOOR_PCT,
)
from .data import (
    POSITIONING_ARCHETYPES,
    PRICE_QUALITY_THRESHOLDS,
    SUCCESSFUL_POSITIONING_EXAMPLES,
    get_archetype,
    get_threshold,
)
from .knowledge import (
    POSITIONING_INSIGHTS,
    POSITIONING_PLAYBOOKS,
    get_insight,
    get_playbook,
)

__all__ = [
    "analyze_market_position",
    "recommend_positioning",
    "detect_positioning_conflicts",
    "estimate_repositioning_effort",
    "RULES",
    "evaluate_rules",
    "POSITION_CONSISTENCY_REQUIRED",
    "MARGIN_FLOOR_PCT",
    "POSITIONING_ARCHETYPES",
    "PRICE_QUALITY_THRESHOLDS",
    "SUCCESSFUL_POSITIONING_EXAMPLES",
    "get_archetype",
    "get_threshold",
    "POSITIONING_INSIGHTS",
    "POSITIONING_PLAYBOOKS",
    "get_insight",
    "get_playbook",
]

MODULE_NAME = "market_position"
MODULE_VERSION = "1.0.0"
MODULE_DESCRIPTION = (
    "Determines optimal market positioning by mapping competitors on a "
    "price-vs-quality matrix, identifying open positions, and recommending "
    "sustainable positioning strategies."
)

REQUIRED_INPUT_FIELDS = [
    "product_category",
    "competitors",
    "our_product",
]

OPTIONAL_INPUT_FIELDS = [
    "current_position",
    "target_margin_pct",
    "catalog",
    "brand_tier",
]

OUTPUT_FIELDS = [
    "landscape",
    "empty_positions",
    "recommended_position",
    "positioning_score",
    "conflicts",
]
