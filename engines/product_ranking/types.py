"""Product Ranking Engine — all TypedDicts and type aliases.

No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class RankingProduct(TypedDict, total=False):
    id: str
    title: str
    composite_score: float
    demand_score: float
    margin_score: float
    competition_score: float
    risk_level: str


class RankingCriteria(TypedDict, total=False):
    demand_weight: float
    margin_weight: float
    competition_weight: float
    risk_penalty: float


class RankingInputData(TypedDict, total=False):
    products: list[RankingProduct]
    criteria: RankingCriteria


class RankedProduct(TypedDict):
    id: str
    title: str
    rank: int
    final_score: float
    weighted_scores: dict[str, float]
    explanation: str


class RankingOutputData(TypedDict):
    ranked_products: list[RankedProduct]
    total_ranked: int
    top_tier_count: int


class RankingMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class RankingOutput(TypedDict):
    status: str
    data: RankingOutputData | None
    meta: RankingMeta
    error: str | None
