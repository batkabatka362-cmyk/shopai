"""Pricing Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the pricing engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductData(TypedDict, total=False):
    """Product information for pricing."""
    title: str
    cogs: float
    shipping_cost: float
    weight_kg: float
    category: str


class MarketData(TypedDict, total=False):
    """Market context for pricing."""
    competitor_prices: list[float]
    avg_market_price: float
    demand_level: str
    category_avg_margin: float


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class CostAnalysis(TypedDict):
    """Full cost breakdown produced by cost_analyzer."""
    cogs: float
    shipping: float
    platform_fees: float
    payment_processing: float
    returns_cost: float
    packaging: float
    total_cost: float
    cost_floor: float


class CompetitorPrices(TypedDict):
    """Competitor price map produced by competitor_price_mapper."""
    min_price: float
    max_price: float
    avg_price: float
    median_price: float
    price_distribution: dict[str, int]
    our_position: str
    competitor_count: int


class ValueEstimate(TypedDict):
    """Perceived value estimate produced by value_estimator."""
    quality_score: float
    brand_strength: float
    uniqueness_score: float
    feature_value: float
    willingness_to_pay: float
    value_confidence: float
    model_note: str


class PriceCalculation(TypedDict):
    """Price calculation result from price_calculator."""
    cost_plus_price: float
    competitive_price: float
    value_based_price: float
    weighted_price: float
    strategy_weights: dict[str, float]
    recommended_strategy: str


class MarginCheck(TypedDict):
    """Margin validation result from margin_validator."""
    margin_at_price: float
    covers_costs: bool
    meets_target: bool
    floor_price: float
    ceiling_price: float
    volume_sensitivity: dict[str, float]
    margin_health: str
    model_note: str


class PsychologyAdjustment(TypedDict):
    """Psychology-optimized price from psychology_optimizer."""
    original_price: float
    adjusted_price: float
    technique_applied: str
    techniques_considered: list[str]
    anchoring_price: float
    framing_suggestion: str
    model_note: str


class PriceRecommendation(TypedDict):
    """Final recommendation from price_recommender."""
    optimal_price: float
    price_range: dict[str, float]
    strategy: str
    rationale: str
    projected_margin: float
    competitive_position: str
    confidence: float
    model_note: str


class ElasticityEstimate(TypedDict):
    """Price elasticity estimate from elasticity_estimator."""
    elasticity_coefficient: float
    sensitivity: str
    optimal_volume_price: float
    price_volume_curve: list[dict[str, float]]
    revenue_maximizing_price: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class PricingOutput(TypedDict):
    """Final output of the pricing engine."""
    status: str
    data: PricingData | None
    meta: PricingMeta
    error: str | None


class PricingData(TypedDict):
    """The 'data' block of the engine output."""
    recommended_price: float
    price_range: dict[str, float]
    strategy: str
    margin_at_recommended: float
    competitive_position: str
    psychology_applied: str
    cost_breakdown: dict[str, float]
    elasticity: dict[str, Any]
    confidence: float
    rationale: str


class PricingMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
