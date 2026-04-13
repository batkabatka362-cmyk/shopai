"""Inventory Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the inventory engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductInventory(TypedDict, total=False):
    """Single product inventory record."""
    id: str
    title: str
    current_stock: int
    daily_sales_avg: float
    lead_time_days: int
    unit_cost: float
    reorder_cost: float


class InventoryInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    products: list[ProductInventory]
    warehouse_capacity: int
    service_level_target: float


# ---------------------------------------------------------------------------
# Intermediate types — stock analysis
# ---------------------------------------------------------------------------

class SKUStockAnalysis(TypedDict):
    """Per-SKU stock analysis from stock_analyzer."""
    id: str
    title: str
    current_stock: int
    daily_sales_avg: float
    days_of_stock: float
    turnover_rate: float
    stock_status: str
    is_dead_stock: bool
    aging_score: float


class StockAnalysisResult(TypedDict):
    """Aggregate result from stock_analyzer."""
    sku_analyses: list[SKUStockAnalysis]
    total_skus: int
    healthy_count: int
    low_count: int
    critical_count: int
    overstocked_count: int
    dead_stock_count: int
    avg_turnover_rate: float
    warehouse_utilization: float


# ---------------------------------------------------------------------------
# Intermediate types — demand forecast
# ---------------------------------------------------------------------------

class SKUDemandForecast(TypedDict):
    """Per-SKU demand forecast from demand_forecaster."""
    id: str
    current_avg: float
    forecast_7d: float
    forecast_30d: float
    trend: str
    seasonality_factor: float
    confidence: float
    model_note: str


# ---------------------------------------------------------------------------
# Intermediate types — reorder calculation
# ---------------------------------------------------------------------------

class SKUReorderCalc(TypedDict):
    """Per-SKU reorder calculation from reorder_calculator."""
    id: str
    reorder_point: int
    economic_order_qty: int
    lead_time_demand: float
    needs_reorder: bool
    units_until_reorder: int
    estimated_reorder_cost: float


# ---------------------------------------------------------------------------
# Intermediate types — safety stock
# ---------------------------------------------------------------------------

class SKUSafetyStock(TypedDict):
    """Per-SKU safety stock from safety_stock_optimizer."""
    id: str
    safety_stock_units: int
    z_score: float
    demand_std_dev: float
    service_level: float
    buffer_days: float
    model_note: str


# ---------------------------------------------------------------------------
# Intermediate types — stockout prediction
# ---------------------------------------------------------------------------

class SKUStockoutRisk(TypedDict):
    """Per-SKU stockout prediction from stockout_predictor."""
    id: str
    title: str
    days_until_stockout: float
    stockout_probability_7d: float
    stockout_probability_30d: float
    risk_level: str
    recommended_action: str


# ---------------------------------------------------------------------------
# Intermediate types — allocation plan
# ---------------------------------------------------------------------------

class SKUAllocation(TypedDict):
    """Per-SKU allocation from allocation_planner."""
    id: str
    title: str
    allocated_stock: int
    allocation_priority: str
    channel_split: dict[str, int]
    model_note: str


# ---------------------------------------------------------------------------
# Intermediate types — alerts
# ---------------------------------------------------------------------------

class InventoryAlert(TypedDict):
    """Single alert from alert_generator."""
    alert_type: str
    severity: str
    sku_id: str
    title: str
    message: str
    recommended_action: str


# ---------------------------------------------------------------------------
# Intermediate types — cost tracking
# ---------------------------------------------------------------------------

class CostSummary(TypedDict):
    """Cost summary from cost_tracker."""
    total_holding_cost: float
    total_ordering_cost: float
    estimated_stockout_cost: float
    total_inventory_value: float
    carrying_cost_pct: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class InventoryHealth(TypedDict):
    """Inventory health summary in engine output."""
    total_skus: int
    healthy_count: int
    low_count: int
    critical_count: int
    overstocked_count: int
    dead_stock_count: int
    avg_turnover_rate: float
    warehouse_utilization: float


class ReorderPlanItem(TypedDict):
    """Single reorder plan item in engine output."""
    id: str
    title: str
    reorder_point: int
    economic_order_qty: int
    safety_stock: int
    needs_reorder: bool
    estimated_cost: float


class InventoryOutput(TypedDict):
    """Final output of the inventory engine."""
    status: str
    data: InventoryData | None
    meta: InventoryMeta
    error: str | None


class InventoryData(TypedDict):
    """The 'data' block of the engine output."""
    inventory_health: InventoryHealth
    reorder_plan: list[ReorderPlanItem]
    stockout_risks: list[SKUStockoutRisk]
    alerts: list[InventoryAlert]
    cost_summary: CostSummary


class InventoryMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
