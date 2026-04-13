"""Dropshipping Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the dropshipping engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class DropshippingInputData(TypedDict, total=False):
    orders: list[dict[str, Any]]
    suppliers: list[dict[str, Any]]
    products: list[dict[str, Any]]
    tracking_data: list[dict[str, Any]]


class SupplierOrder(TypedDict):
    order_id: str
    supplier_id: str
    supplier_name: str
    items: list[dict[str, Any]]
    total_cost: float
    status: str


class TrackingUpdate(TypedDict):
    order_id: str
    tracking_number: str
    carrier: str
    status: str
    estimated_delivery: str


class MarginAnalysis(TypedDict):
    product_id: str
    supplier_id: str
    cost: float
    selling_price: float
    margin: float
    margin_pct: float


class SupplierPerformance(TypedDict):
    supplier_id: str
    supplier_name: str
    avg_fulfillment_days: float
    on_time_rate: float
    defect_rate: float
    overall_score: float


class DropshippingData(TypedDict):
    supplier_orders: list[SupplierOrder]
    tracking_updates: list[TrackingUpdate]
    margin_analysis: list[MarginAnalysis]
    supplier_performance: list[SupplierPerformance]


class DropshippingMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class DropshippingOutput(TypedDict):
    status: str
    data: DropshippingData | None
    meta: DropshippingMeta
    error: str | None
