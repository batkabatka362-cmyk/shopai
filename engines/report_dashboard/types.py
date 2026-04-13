"""Report Dashboard Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the report dashboard engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class ReportDashboardInputData(TypedDict, total=False):
    period: str
    data_sources: list[str]
    format: str


class AggregatedData(TypedDict):
    source: str
    records_count: int
    summary: dict[str, Any]


class DashboardMetric(TypedDict):
    name: str
    value: float
    previous_value: float
    change_pct: float
    trend: str


class ChartData(TypedDict):
    chart_type: str
    title: str
    labels: list[str]
    datasets: list[dict[str, Any]]


class PeriodComparison(TypedDict):
    current_period: str
    previous_period: str
    metrics: list[DashboardMetric]


class ReportDashboardData(TypedDict):
    dashboard: dict[str, Any]
    period_comparison: PeriodComparison
    highlights: list[str]
    action_items: list[str]


class ReportDashboardMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class ReportDashboardOutput(TypedDict):
    status: str
    data: ReportDashboardData | None
    meta: ReportDashboardMeta
    error: str | None
