"""Upsell Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the upsell engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CurrentProduct(TypedDict, total=False):
    """The product currently being viewed or added to cart."""
    id: str
    title: str
    category: str
    price: float
    tier: str                       # free, basic, standard, premium, pro, enterprise
    features: list[str]


class CustomerProfile(TypedDict, total=False):
    """Customer context for upsell targeting."""
    avg_order_value: float
    total_orders: int
    price_sensitivity: float        # 0.0 (insensitive) to 1.0 (very sensitive)


class CatalogProduct(TypedDict, total=False):
    """A candidate product from the catalog."""
    id: str
    title: str
    category: str
    price: float
    tier: str
    features: list[str]
    margin: float                   # gross margin as decimal (0.0 - 1.0)


class UpsellInputData(TypedDict, total=False):
    """Top-level input data block."""
    current_product: CurrentProduct
    customer: CustomerProfile
    catalog: list[CatalogProduct]


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class ProductAnalysis(TypedDict):
    """Output from product_analyzer: understanding of the current product."""
    product_id: str
    title: str
    category: str
    price: float
    tier: str
    tier_rank: int                  # numeric rank (1=lowest, 5=highest)
    feature_count: int
    price_position: str             # budget, mid_range, premium, luxury
    has_upgrade_room: bool
    margin_headroom: float          # estimated margin room for discounting upsell


class UpgradeCandidate(TypedDict):
    """A single upgrade candidate from upgrade_finder."""
    product_id: str
    title: str
    category: str
    price: float
    tier: str
    tier_rank: int
    features: list[str]
    margin: float
    tier_jump: int                  # how many tiers above current
    extra_features: list[str]       # features current product lacks
    relevance_score: float          # 0-1 composite relevance
    model_note: str                 # Mistral reasoning


class PriceGapAnalysis(TypedDict):
    """Price gap analysis for a single candidate."""
    product_id: str
    absolute_difference: float      # dollars
    percentage_increase: float      # as decimal (0.25 = 25%)
    under_10_dollars: bool          # psychological threshold
    under_30_percent: bool          # psychological threshold
    in_sweet_spot: bool             # acceptable gap for upsell
    psychological_score: float      # 0-1 how psychologically acceptable
    per_day_cost_increase: float    # assuming 365-day product life
    anchoring_effect: float         # how well original price anchors perception


class ValueProposition(TypedDict):
    """Value proposition for a single upsell candidate."""
    product_id: str
    headline: str                   # one-line value hook
    feature_comparison: list[str]   # "Current lacks X, upgrade has X"
    per_day_framing: str            # "Just $0.14/day more"
    roi_justification: str          # ROI angle
    social_proof: str               # social proof angle
    model_note: str                 # LLaMA reasoning


class ConversionEstimate(TypedDict):
    """Conversion probability estimate for a single candidate."""
    product_id: str
    base_probability: float         # from price gap alone
    customer_adjustment: float      # modifier from customer history
    category_adjustment: float      # modifier from category norms
    final_probability: float        # combined estimate 0-1
    confidence: float               # how confident in the estimate


class TimingRecommendation(TypedDict):
    """When and where to show the upsell."""
    product_id: str
    best_timing: str                # product_page, cart, checkout, post_purchase, email_followup
    all_timings: list[dict[str, Any]]  # [{timing: str, score: float}, ...]
    urgency_level: str              # low, medium, high
    rationale: str


class UpsellRecommendation(TypedDict):
    """Final recommendation for a single upsell candidate."""
    product_id: str
    title: str
    price_increase: float           # absolute dollar increase
    value_proposition: str          # headline message
    conversion_probability: float
    expected_revenue: float         # price_increase * conversion_probability
    timing: str                     # best timing
    messaging: dict[str, str]       # headline, body, cta
    placement: str                  # where to show
    model_note: str                 # Qwen reasoning


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class UpsellData(TypedDict):
    """The 'data' block of the engine output."""
    upsells: list[UpsellRecommendation]
    best_upsell: UpsellRecommendation | None
    estimated_revenue_increase: float
    confidence: float


class UpsellMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
    candidates_evaluated: int
    candidates_recommended: int


class UpsellOutput(TypedDict):
    """Final output of the upsell engine."""
    status: str
    data: UpsellData | None
    meta: UpsellMeta
    error: str | None
