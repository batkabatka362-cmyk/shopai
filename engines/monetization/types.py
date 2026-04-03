"""Monetization Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the monetization engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class MonetizationInputData(TypedDict, total=False):
    products: list[dict[str, Any]]
    customers: list[dict[str, Any]]
    revenue_data: dict[str, Any]


class RevenueOpportunity(TypedDict):
    type: str
    potential_revenue: float
    effort: str
    description: str


class MonetizationData(TypedDict):
    opportunities: list[RevenueOpportunity]
    recommended_models: list[str]
    projected_uplift: float


class MonetizationMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class MonetizationOutput(TypedDict):
    status: str
    data: MonetizationData | None
    meta: MonetizationMeta
    error: str | None
