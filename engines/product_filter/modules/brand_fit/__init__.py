"""
brand_fit — Evaluate whether a product fits the store's brand identity.

Scores products 0-100 on brand alignment considering price tier,
category coherence, quality level, target demographic, and brand
values.  Products scoring below 40 are flagged as poor fit.
"""

from .code import check_brand_fit
from .logic import (
    recommend_brand_positioning,
    detect_brand_dilution,
    suggest_brand_aligned_alternatives,
)
from .rules import (
    BRAND_COHERENCE_RULES,
    QUALITY_TIERS,
    MAX_CATEGORIES_NEW_STORE,
    get_price_variance_limit,
)
from .data import (
    BRAND_ARCHETYPES,
    TARGET_DEMOGRAPHICS,
    BRAND_VALUE_KEYWORDS,
    get_archetype_profile,
)
from .knowledge import (
    BRAND_HEURISTICS,
    diagnose_brand_issues,
    get_brand_tips,
)

__all__ = [
    "check_brand_fit",
    "recommend_brand_positioning",
    "detect_brand_dilution",
    "suggest_brand_aligned_alternatives",
    "BRAND_COHERENCE_RULES",
    "QUALITY_TIERS",
    "MAX_CATEGORIES_NEW_STORE",
    "get_price_variance_limit",
    "BRAND_ARCHETYPES",
    "TARGET_DEMOGRAPHICS",
    "BRAND_VALUE_KEYWORDS",
    "get_archetype_profile",
    "BRAND_HEURISTICS",
    "diagnose_brand_issues",
    "get_brand_tips",
]
