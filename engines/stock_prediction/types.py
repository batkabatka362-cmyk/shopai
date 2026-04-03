"""Stock Prediction Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the stock prediction engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductStock(TypedDict, total=False):
    """Single product stock record."""
    id: str
    title: str
    current_stock: int
    daily_sales_avg: float
    unit_cost: float


class SupplierInfo(TypedDict, total=False):
    """Supplier information."""
    id: str
    name: str
    lead_time_days: int
    reliability_score: float


class OrderHistory(TypedDict, total=False):
    """Single order history record."""
    order_id: str
    product_id: str
    quantity: int
    date: str


class StockPredictionInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    products: list[ProductStock]
    orders_history: list[OrderHistory]
    suppliers: list[SupplierInfo]
    current_stock: dict[str, int]


# ---------------------------------------------------------------------------
# Intermediate types — demand modeling
# ---------------------------------------------------------------------------

class DemandModel(TypedDict):
    """Per-product demand model from demand_modeler."""
    product_id: str
    avg_daily_demand: float
    demand_trend: str
    demand_volatility: float
    model_confidence: float


# ---------------------------------------------------------------------------
# Intermediate types — seasonality
# ---------------------------------------------------------------------------

class SeasonalFactor(TypedDict):
    """Seasonal factor for a product."""
    product_id: str
    peak_months: list[int]
    seasonal_index: dict[str, float]
    seasonality_strength: float


# ---------------------------------------------------------------------------
# Intermediate types — lead time
# ---------------------------------------------------------------------------

class LeadTimeEstimate(TypedDict):
    """Lead time estimate for a product-supplier pair."""
    product_id: str
    supplier_id: str
    avg_lead_time_days: int
    lead_time_std_dev: float
    reliability: float


# ---------------------------------------------------------------------------
# Intermediate types — restock recommendation
# ---------------------------------------------------------------------------

class RestockRecommendation(TypedDict):
    """Per-product restock recommendation."""
    product_id: str
    predicted_demand_30d: float
    predicted_demand_90d: float
    restock_date: str
    restock_qty: int
    urgency: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class PredictionItem(TypedDict):
    """Single prediction item in engine output."""
    product_id: str
    predicted_demand_30d: float
    predicted_demand_90d: float
    restock_date: str
    restock_qty: int


class StockPredictionData(TypedDict):
    """The 'data' block of engine output."""
    predictions: list[PredictionItem]
    seasonal_factors: list[SeasonalFactor]
    confidence: float


class StockPredictionMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class StockPredictionOutput(TypedDict):
    """Final output of the stock prediction engine."""
    status: str
    data: StockPredictionData | None
    meta: StockPredictionMeta
    error: str | None
