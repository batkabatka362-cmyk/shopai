"""Competitor Ad Intelligence Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the competitor ad intelligence engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class AdIntelInputData(TypedDict, total=False):
    competitors: list[dict[str, Any]]
    platforms: list[str]
    period: str


class DetectedAd(TypedDict):
    competitor: str
    platform: str
    ad_type: str
    headline: str
    estimated_impressions: int
    first_seen: str


class SpendEstimate(TypedDict):
    competitor: str
    platform: str
    estimated_monthly_spend: float
    confidence: str


class CreativePattern(TypedDict):
    competitor: str
    pattern_type: str
    frequency: int
    description: str


class AdIntelData(TypedDict):
    ads_detected: list[DetectedAd]
    spend_estimates: list[SpendEstimate]
    creative_patterns: list[CreativePattern]
    strategy_report: dict[str, Any]
    our_gaps: list[str]


class AdIntelMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class AdIntelOutput(TypedDict):
    status: str
    data: AdIntelData | None
    meta: AdIntelMeta
    error: str | None
