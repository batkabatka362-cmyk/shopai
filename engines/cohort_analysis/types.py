"""Cohort Analysis Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the cohort analysis engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class CohortInputData(TypedDict, total=False):
    customers: list[dict[str, Any]]
    orders: list[dict[str, Any]]
    cohort_type: str


class Cohort(TypedDict):
    period: str
    size: int
    retention_rates: list[float]
    revenue: float
    ltv: float


class CohortData(TypedDict):
    cohorts: list[Cohort]
    retention_matrix: list[list[float]]
    best_cohort: str
    trends: dict[str, Any]


class CohortMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class CohortOutput(TypedDict):
    status: str
    data: CohortData | None
    meta: CohortMeta
    error: str | None
