"""Ranking Module — ranks products by unified score and identifies tiers.

Sorts products by their aggregated unified score, assigns ranks,
calculates score gaps, groups into tiers, and identifies clear winners
versus too-close-to-call situations.
"""

from .code import rank_products
from .logic import (
    identify_clear_winner,
    assess_ranking_stability,
    recommend_shortlist_size,
)
from .rules import validate_ranking_inputs, RANKING_RULES
from .data import (
    TIER_BOUNDARIES,
    SCORE_GAP_THRESHOLDS,
    RANKING_STABILITY_METRICS,
    MINIMUM_VIABLE_SCORE,
)
from .knowledge import RANKING_KNOWLEDGE, get_ranking_insight

__all__ = [
    "rank_products",
    "identify_clear_winner",
    "assess_ranking_stability",
    "recommend_shortlist_size",
    "validate_ranking_inputs",
    "RANKING_RULES",
    "TIER_BOUNDARIES",
    "SCORE_GAP_THRESHOLDS",
    "RANKING_STABILITY_METRICS",
    "MINIMUM_VIABLE_SCORE",
    "RANKING_KNOWLEDGE",
    "get_ranking_insight",
]
