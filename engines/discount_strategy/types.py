"""Discount Strategy Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the discount strategy engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductInput(TypedDict, total=False):
    """Single product submitted for discount evaluation."""
    id: str
    title: str
    price: float
    cogs: float
    current_margin: float
    daily_sales: float


class DiscountInput(TypedDict, total=False):
    """Top-level input data block."""
    products: list[ProductInput]
    goal: str                       # clear_inventory, boost_revenue, acquire_customers, reactivate
    inventory_days: int             # days of inventory remaining
    customer_segments: list[str]    # e.g. ["vip", "at_risk", "new"]


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class MarginAnalysis(TypedDict):
    """Per-product margin analysis from margin_analyzer."""
    product_id: str
    title: str
    price: float
    cogs: float
    current_margin: float
    max_discount_pct: float         # deepest discount before hitting floor
    margin_floor: float             # minimum acceptable margin
    safe_discount_room: float       # percentage points of safe discount headroom
    margin_health: str              # excellent, healthy, thin, critical


class DiscountTypeSelection(TypedDict):
    """Discount type selected by discount_type_selector."""
    selected_type: str              # percentage_off, dollar_off, bogo, free_shipping, bundle_deal, tiered
    rationale: str
    alternatives: list[str]
    goal_alignment: float           # 0-1
    model_note: str


class DepthCalculation(TypedDict):
    """Optimal depth calculation from depth_calculator."""
    min_depth_pct: float            # minimum to trigger customer action
    max_depth_pct: float            # maximum before margin erosion
    sweet_spot_pct: float           # optimal discount depth
    expected_volume_lift: float     # multiplier on current volume
    margin_at_sweet_spot: float     # margin after discount
    depth_rationale: str


class TargetSelection(TypedDict):
    """Target audience selection from target_selector."""
    target_audience: str            # all, vip, at_risk, new_customers, high_value, segment_specific
    segment_rationale: str
    estimated_reach_pct: float      # % of customer base reached
    expected_response_rate: float   # expected conversion rate from segment
    model_note: str


class DurationPlan(TypedDict):
    """Duration plan from duration_planner."""
    duration_hours: int
    duration_label: str             # flash, daily, weekend, weekly, seasonal
    start_time: str                 # recommended start window
    urgency_score: float            # 0-1
    urgency_rationale: str


class CannibalizationCheck(TypedDict):
    """Cannibalization analysis from cannibalization_checker."""
    cannibalization_risk: str       # low, medium, high
    regular_sales_impact_pct: float # expected % drop in full-price sales
    brand_perception_impact: str    # none, slight, moderate, significant
    forward_buying_risk: str        # low, medium, high
    risk_rationale: str


class RevenueProjection(TypedDict):
    """Revenue impact projection from revenue_projector."""
    base_revenue_daily: float
    projected_revenue_daily: float
    revenue_change_pct: float
    margin_loss_per_unit: float
    volume_lift_multiplier: float
    break_even_volume: float        # units needed to break even
    break_even_achievable: bool
    net_profit_impact: float
    projection_confidence: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class DiscountStrategy(TypedDict):
    """The core strategy recommendation."""
    type: str
    depth_pct: float
    target_audience: str
    duration_hours: int
    start_time: str


class MarginImpact(TypedDict):
    """Margin impact summary."""
    current_margin: float
    discounted_margin: float
    margin_loss_pct: float
    max_safe_discount: float


class ProjectedRevenue(TypedDict):
    """Projected revenue summary."""
    base_daily: float
    projected_daily: float
    change_pct: float
    break_even_volume: float
    break_even_achievable: bool
    net_profit_impact: float


class DiscountStrategyData(TypedDict):
    """The 'data' block of the engine output."""
    strategy: DiscountStrategy
    margin_impact: MarginImpact
    projected_revenue: ProjectedRevenue
    cannibalization_risk: str
    confidence: float


class DiscountStrategyMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class DiscountStrategyOutput(TypedDict):
    """Final output of the discount strategy engine."""
    status: str
    data: DiscountStrategyData | None
    meta: DiscountStrategyMeta
    error: str | None
