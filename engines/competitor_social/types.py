"""Competitor Social Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the competitor social engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class SocialInputData(TypedDict, total=False):
    competitors: list[dict[str, Any]]
    platforms: list[str]
    our_metrics: dict[str, Any]


class CompetitorProfile(TypedDict):
    competitor: str
    platform: str
    followers: int
    posts_per_week: float
    avg_engagement_rate: float


class EngagementComparison(TypedDict):
    platform: str
    our_rate: float
    avg_competitor_rate: float
    best_competitor: str
    best_rate: float
    our_rank: int


class ContentBreakdown(TypedDict):
    competitor: str
    platform: str
    content_types: dict[str, float]


class SocialBenchmark(TypedDict):
    metric: str
    our_value: float
    industry_avg: float
    top_performer: float
    percentile: int


class SocialData(TypedDict):
    competitor_profiles: list[CompetitorProfile]
    engagement_comparison: list[EngagementComparison]
    content_breakdown: list[ContentBreakdown]
    benchmarks: list[SocialBenchmark]
    recommendations: list[str]


class SocialMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class SocialOutput(TypedDict):
    status: str
    data: SocialData | None
    meta: SocialMeta
    error: str | None
