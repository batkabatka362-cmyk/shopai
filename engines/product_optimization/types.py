"""Product Optimization Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the product optimization engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class OptimizationProduct(TypedDict, total=False):
    """Single product for optimization."""
    id: str
    title: str
    category: str
    price: float
    description: str
    tags: list[str]


class PerformanceRecord(TypedDict, total=False):
    """Product performance data."""
    product_id: str
    units_sold: int
    revenue: float
    conversion_rate: float
    return_rate: float
    avg_rating: float
    views: int


class OptimizationInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    products: list[OptimizationProduct]
    performance_data: list[PerformanceRecord]


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class PerformanceAnalysis(TypedDict):
    """Per-product performance analysis from performance_analyzer."""
    product_id: str
    revenue_rank: int
    conversion_score: float
    return_score: float
    overall_score: float
    weaknesses: list[str]


class ImprovementOpportunity(TypedDict):
    """Per-product improvement from improvement_finder."""
    product_id: str
    improvement_type: str
    recommendation: str
    expected_impact: float
    priority: str


class PriceAdjustment(TypedDict):
    """Per-product price adjustment from price_adjuster."""
    product_id: str
    current_price: float
    suggested_price: float
    adjustment_pct: float
    rationale: str


class ListingEnhancement(TypedDict):
    """Per-product listing enhancement from listing_enhancer."""
    product_id: str
    enhancement_type: str
    suggestion: str
    expected_conversion_lift: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class OptimizationItem(TypedDict):
    """Single optimization recommendation in output."""
    product_id: str
    type: str
    recommendation: str
    expected_impact: float


class OptimizationData(TypedDict):
    """The 'data' block of the engine output."""
    optimizations: list[OptimizationItem]


class OptimizationMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class OptimizationOutput(TypedDict):
    """Final output of the product optimization engine."""
    status: str
    data: OptimizationData | None
    meta: OptimizationMeta
    error: str | None
