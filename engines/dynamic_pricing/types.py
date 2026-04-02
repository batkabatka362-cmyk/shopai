"""Dynamic Pricing Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the dynamic pricing engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductInput(TypedDict, total=False):
    """Single product to evaluate for price adjustment."""
    id: str
    current_price: float
    cogs: float
    daily_sales: float


class MarketSignals(TypedDict, total=False):
    """Market-level signals for dynamic pricing."""
    demand_index: float
    competitor_prices: dict[str, float]
    inventory_days: float
    season: str


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class CollectedSignals(TypedDict):
    """Signals gathered by signal_collector for a single product."""
    product_id: str
    current_price: float
    cogs: float
    daily_sales: float
    demand_index: float
    competitor_prices: list[float]
    inventory_days: float
    season: str


class DemandAnalysis(TypedDict):
    """Demand analysis produced by demand_analyzer."""
    demand_ratio: float
    surge_detected: bool
    trend_direction: str
    demand_multiplier: float
    model_note: str


class CompetitionSnapshot(TypedDict):
    """Competition snapshot produced by competition_monitor."""
    avg_competitor_price: float
    min_competitor_price: float
    max_competitor_price: float
    competitor_count: int
    our_position: str
    price_gap_pct: float
    competitive_pressure: float


class InventoryAssessment(TypedDict):
    """Inventory assessment produced by inventory_assessor."""
    days_of_stock: float
    stockout_risk: float
    overstock_risk: float
    urgency_level: str
    inventory_multiplier: float


class TimeFactors(TypedDict):
    """Time factor analysis produced by time_factor_analyzer."""
    day_of_week: str
    hour: int
    season: str
    is_holiday: bool
    is_weekend: bool
    time_multiplier: float
    model_note: str


class PriceAdjustment(TypedDict):
    """Single product price adjustment from price_adjuster."""
    product_id: str
    current_price: float
    new_price: float
    change_pct: float
    raw_multiplier: float
    signal_weights: dict[str, float]


class ImpactEstimate(TypedDict):
    """Impact estimate for a single adjustment from impact_estimator."""
    product_id: str
    current_price: float
    new_price: float
    change_pct: float
    estimated_daily_revenue_before: float
    estimated_daily_revenue_after: float
    estimated_revenue_change: float
    estimated_margin_before: float
    estimated_margin_after: float
    volume_sensitivity: float
    reason: str


class ValidationResult(TypedDict):
    """Validation result from change_validator."""
    product_id: str
    current_price: float
    new_price: float
    change_pct: float
    approved: bool
    rejection_reason: str | None
    reversible: bool
    model_note: str


# ---------------------------------------------------------------------------
# Engine output types
# ---------------------------------------------------------------------------

class AdjustmentOutput(TypedDict):
    """Single adjustment in the engine output."""
    product_id: str
    current_price: float
    new_price: float
    change_pct: float
    reason: str


class AdjustmentSummary(TypedDict):
    """Summary of all adjustments."""
    total_adjustments: int
    avg_change_pct: float
    estimated_revenue_impact: float


class DynamicPricingData(TypedDict):
    """The 'data' block of the engine output."""
    adjustments: list[AdjustmentOutput]
    summary: AdjustmentSummary


class DynamicPricingMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class DynamicPricingOutput(TypedDict):
    """Final output of the dynamic pricing engine."""
    status: str
    data: DynamicPricingData | None
    meta: DynamicPricingMeta
    error: str | None
