"""Cashflow Simulator Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the cashflow simulator engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class CashflowInputData(TypedDict, total=False):
    current_balance: float
    monthly_revenue: float
    monthly_costs: float
    growth_rate: float
    seasonality: dict[str, float]


class MonthlyProjection(TypedDict):
    month: int
    month_label: str
    revenue: float
    costs: float
    net: float
    balance: float


class ScenarioProjection(TypedDict):
    name: str
    projections: list[MonthlyProjection]
    final_balance: float
    total_revenue: float
    total_costs: float


class Viability(TypedDict):
    runway_months: int
    break_even_month: int
    risk: str
    notes: list[str]


class CashflowData(TypedDict):
    projections: list[MonthlyProjection]
    scenarios: dict[str, ScenarioProjection]
    viability: Viability


class CashflowMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class CashflowOutput(TypedDict):
    status: str
    data: CashflowData | None
    meta: CashflowMeta
    error: str | None
