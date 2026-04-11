"""Profitability Calculator Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the profitability calculator engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProfitProduct(TypedDict, total=False):
    """Single product for profitability analysis."""
    id: str
    title: str
    price: float
    units_sold: int


class CostRecord(TypedDict, total=False):
    """Cost record for a product."""
    product_id: str
    cogs: float
    shipping_cost: float
    marketing_cost: float
    platform_fee: float
    overhead_allocation: float


class PricingRecord(TypedDict, total=False):
    """Pricing record for a product."""
    product_id: str
    selling_price: float
    discount_pct: float
    effective_price: float


class ProfitabilityInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    products: list[ProfitProduct]
    costs: list[CostRecord]
    pricing: list[PricingRecord]


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class CostBreakdownItem(TypedDict):
    """Per-product cost breakdown from cost_breakdown."""
    product_id: str
    cogs: float
    shipping: float
    marketing: float
    platform_fee: float
    overhead: float
    total_cost_per_unit: float


class MarginResult(TypedDict):
    """Per-product margin from margin_calculator."""
    product_id: str
    revenue_per_unit: float
    cost_per_unit: float
    gross_margin: float
    gross_margin_pct: float
    net_margin: float
    net_margin_pct: float


class BreakEvenResult(TypedDict):
    """Per-product break-even from break_even_analyzer."""
    product_id: str
    break_even_units: int
    break_even_revenue: float
    units_above_break_even: int
    is_profitable: bool


class ROIProjection(TypedDict):
    """Per-product ROI from roi_projector."""
    product_id: str
    total_investment: float
    total_return: float
    roi_pct: float
    payback_periods: int


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ProfitabilityItem(TypedDict):
    """Single product profitability result in output."""
    product_id: str
    revenue: float
    total_cost: float
    net_margin: float
    break_even_units: int
    roi: float


class ProfitabilityData(TypedDict):
    """The 'data' block of the engine output."""
    profitability: list[ProfitabilityItem]


class ProfitabilityMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class ProfitabilityOutput(TypedDict):
    """Final output of the profitability calculator engine."""
    status: str
    data: ProfitabilityData | None
    meta: ProfitabilityMeta
    error: str | None
