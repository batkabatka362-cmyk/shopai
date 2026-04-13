"""KPI Tracking Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the KPI tracking engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class OrderRecord(TypedDict, total=False):
    """Single order record."""
    id: str
    customer_id: str
    total: float
    date: str
    products: list[str]
    channel: str


class CustomerRecord(TypedDict, total=False):
    """Single customer record."""
    id: str
    first_order_date: str
    total_orders: int
    total_spent: float
    acquisition_cost: float


class CostRecord(TypedDict, total=False):
    """Cost record for a period."""
    category: str
    amount: float
    date: str
    description: str


class BenchmarkRecord(TypedDict, total=False):
    """Industry benchmark for a KPI."""
    kpi: str
    industry_avg: float
    top_quartile: float
    bottom_quartile: float


class KpiTrackingInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    orders: list[OrderRecord]
    customers: list[CustomerRecord]
    costs: list[CostRecord]
    period: str
    benchmarks: list[BenchmarkRecord]


# ---------------------------------------------------------------------------
# Intermediate types — KPI calculation
# ---------------------------------------------------------------------------

class KPIValues(TypedDict):
    """Calculated KPI values."""
    aov: float
    cac: float
    ltv: float
    conversion_rate: float
    revenue: float
    order_count: int
    customer_count: int
    repeat_rate: float
    gross_margin: float


# ---------------------------------------------------------------------------
# Intermediate types — trend analysis
# ---------------------------------------------------------------------------

class KPITrend(TypedDict):
    """Trend for a single KPI."""
    kpi: str
    direction: str
    change_pct: float
    current_value: float
    previous_value: float


# ---------------------------------------------------------------------------
# Intermediate types — benchmark comparison
# ---------------------------------------------------------------------------

class BenchmarkComparison(TypedDict):
    """Comparison of a KPI against industry benchmark."""
    kpi: str
    current_value: float
    industry_avg: float
    percentile: str
    gap: float


# ---------------------------------------------------------------------------
# Intermediate types — alert checking
# ---------------------------------------------------------------------------

class KPIAlert(TypedDict):
    """Alert when a KPI crosses a threshold."""
    kpi: str
    severity: str
    message: str
    current_value: float
    threshold: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class KpiTrackingData(TypedDict):
    """The 'data' block of engine output."""
    kpis: KPIValues
    trends: list[KPITrend]
    alerts: list[KPIAlert]
    health_grade: str


class KpiTrackingMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class KpiTrackingOutput(TypedDict):
    """Final output of the KPI tracking engine."""
    status: str
    data: KpiTrackingData | None
    meta: KpiTrackingMeta
    error: str | None
