"""Shipping Optimization Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the shipping optimization engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductDimensions(TypedDict, total=False):
    """Package dimensions in centimetres."""
    l: float
    w: float
    h: float


class ProductItem(TypedDict, total=False):
    """A single product in the input payload."""
    id: str
    weight_kg: float
    dimensions: ProductDimensions
    price: float


class ShippingInputData(TypedDict, total=False):
    """The 'data' block of the engine input."""
    products: list[ProductItem]
    origin_zip: str
    avg_order_value: float
    monthly_orders: int
    current_shipping_strategy: str


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class ShippingRate(TypedDict):
    """A computed shipping rate for one carrier / service level."""
    carrier: str
    service: str
    rate: float
    zone: int
    weight_kg: float
    dimensional_weight_kg: float
    billable_weight_kg: float
    surcharges: float
    total: float


class CarrierComparison(TypedDict):
    """Comparison row for one carrier + service level."""
    carrier: str
    service: str
    rate: float
    transit_days_min: int
    transit_days_max: int
    reliability_score: float
    value_score: float
    best_for: str


class ThresholdResult(TypedDict):
    """Free-shipping threshold optimisation result."""
    recommended_threshold: float
    current_aov: float
    target_aov: float
    orders_qualifying_pct: float
    avg_shipping_cost_absorbed: float
    incremental_revenue: float
    net_profit_impact: float
    confidence: float


class DeliveryEstimate(TypedDict):
    """Delivery time estimate for one carrier + zone."""
    carrier: str
    service: str
    zone: int
    business_days_min: int
    business_days_max: int
    calendar_days_min: int
    calendar_days_max: int


class CostAllocation(TypedDict):
    """How shipping cost is allocated for a strategy."""
    strategy: str
    merchant_absorbs: float
    customer_pays: float
    built_into_price: float
    total_shipping_cost: float
    effective_margin_impact: float


class ZoneDistribution(TypedDict):
    """Shipping zone distribution for a given origin."""
    zone: int
    pct_of_orders: float
    avg_rate: float
    avg_transit_days: float


class ShippingStrategy(TypedDict):
    """A recommended shipping strategy."""
    strategy_id: str
    name: str
    description: str
    type: str
    parameters: dict[str, Any]
    expected_monthly_cost: float
    expected_monthly_revenue_lift: float
    expected_monthly_profit_impact: float
    confidence: float
    reasoning: list[str]
    model_note: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ShippingOptimizationOutput(TypedDict):
    """Final output of the shipping optimization engine."""
    status: str
    data: ShippingOptimizationData | None
    meta: ShippingOptimizationMeta
    error: str | None


class ShippingOptimizationData(TypedDict):
    """The 'data' block of the engine output."""
    recommended_strategy: dict[str, Any]
    carrier_comparison: list[dict[str, Any]]
    free_shipping_threshold: float
    estimated_savings_monthly: float
    delivery_times: dict[str, Any]
    confidence: float


class ShippingOptimizationMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
