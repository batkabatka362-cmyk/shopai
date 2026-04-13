"""Financial Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the financial engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class FinancialInputData(TypedDict, total=False):
    orders: list[dict[str, Any]]
    products: list[dict[str, Any]]
    costs: dict[str, Any]
    period: str


class RevenueBreakdown(TypedDict):
    total_revenue: float
    order_count: int
    avg_order_value: float
    revenue_per_product: dict[str, float]


class CostBreakdown(TypedDict):
    total_cogs: float
    total_operating: float
    total_costs: float
    cost_per_order: float


class MarginResult(TypedDict):
    gross_margin_pct: float
    net_margin_pct: float
    contribution_margin: float
    margin_by_product: list[dict[str, Any]]


class HealthGrade(TypedDict):
    grade: str
    score: float
    factors: dict[str, float]
    recommendations: list[str]


class FinancialData(TypedDict):
    revenue: RevenueBreakdown
    costs: CostBreakdown
    margins: MarginResult
    health_grade: HealthGrade
    pnl_summary: dict[str, Any]


class FinancialMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class FinancialOutput(TypedDict):
    status: str
    data: FinancialData | None
    meta: FinancialMeta
    error: str | None
