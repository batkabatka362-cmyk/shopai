"""Opportunity Detection Engine — all TypedDicts and type aliases."""
from __future__ import annotations
from typing import Any, TypedDict


class OpportunityDetectionInputData(TypedDict, total=False):
    market_data: dict[str, Any]
    competition: list[dict[str, Any]]
    trends: list[dict[str, Any]]


class MarketGap(TypedDict):
    gap: str
    demand: float
    feasibility: float
    priority: str


class OpportunityDetectionData(TypedDict):
    opportunities: list[MarketGap]
    top_opportunity: MarketGap


class OpportunityDetectionMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class OpportunityDetectionOutput(TypedDict):
    status: str
    data: OpportunityDetectionData | None
    meta: OpportunityDetectionMeta
    error: str | None
