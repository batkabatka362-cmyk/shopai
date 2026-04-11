"""NPS Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the NPS engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class NpsInputData(TypedDict, total=False):
    responses: list[dict[str, Any]]
    segments: list[dict[str, Any]]


class SegmentBreakdown(TypedDict):
    segment: str
    nps_score: float
    promoters_pct: float
    passives_pct: float
    detractors_pct: float
    response_count: int


class NpsTrend(TypedDict):
    period: str
    nps_score: float
    response_count: int


class NpsData(TypedDict):
    nps_score: float
    promoters_pct: float
    passives_pct: float
    detractors_pct: float
    segment_breakdown: list[SegmentBreakdown]
    trends: list[NpsTrend]
    action_items: list[str]


class NpsMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class NpsOutput(TypedDict):
    status: str
    data: NpsData | None
    meta: NpsMeta
    error: str | None
