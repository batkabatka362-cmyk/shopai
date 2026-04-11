"""Price Elasticity Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the price elasticity engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ElasticityProduct(TypedDict, total=False):
    """Single product for elasticity analysis."""
    id: str
    title: str
    category: str
    current_price: float


class PriceHistoryItem(TypedDict, total=False):
    """Single price history record."""
    product_id: str
    period: str
    price: float
    units_sold: int
    revenue: float


class SalesDataItem(TypedDict, total=False):
    """Sales data for elasticity calculation."""
    product_id: str
    period: str
    units_sold: int
    revenue: float


class ElasticityInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    products: list[ElasticityProduct]
    price_history: list[PriceHistoryItem]
    sales_data: list[SalesDataItem]


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class SensitivityResult(TypedDict):
    """Per-product sensitivity from sensitivity_calculator."""
    product_id: str
    elasticity_coefficient: float
    is_elastic: bool
    sensitivity_band: str


class DemandCurvePoint(TypedDict):
    """Single point on a demand curve."""
    price: float
    predicted_demand: int


class DemandCurve(TypedDict):
    """Per-product demand curve from demand_curve_builder."""
    product_id: str
    curve_points: list[DemandCurvePoint]
    r_squared: float


class OptimalPriceResult(TypedDict):
    """Per-product optimal price from optimal_price_finder."""
    product_id: str
    optimal_price: float
    expected_units: int
    expected_revenue: float
    current_revenue_gap: float


class SegmentAnalysis(TypedDict):
    """Per-product segment analysis from segment_analyzer."""
    product_id: str
    segment: str
    segment_elasticity: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ElasticityItem(TypedDict):
    """Single product elasticity result in output."""
    product_id: str
    coefficient: float
    optimal_price: float
    expected_revenue: float
    is_elastic: bool


class ElasticityData(TypedDict):
    """The 'data' block of the engine output."""
    elasticity: list[ElasticityItem]


class ElasticityMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class ElasticityOutput(TypedDict):
    """Final output of the price elasticity engine."""
    status: str
    data: ElasticityData | None
    meta: ElasticityMeta
    error: str | None
