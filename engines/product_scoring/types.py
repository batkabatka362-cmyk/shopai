"""Product Scoring Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the product scoring engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ScoringProduct(TypedDict, total=False):
    """Single product to score."""
    id: str
    title: str
    category: str
    sale_price: float
    unit_cost: float
    daily_sales_avg: float
    competitor_count: int
    review_rating: float
    trend_direction: str


class ScoringCriteria(TypedDict, total=False):
    """Weights and thresholds for scoring."""
    demand_weight: float
    margin_weight: float
    competition_weight: float
    trend_weight: float


class ScoringInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    products: list[ScoringProduct]
    criteria: ScoringCriteria


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class DemandScore(TypedDict):
    """Per-product demand score."""
    id: str
    score: float
    daily_velocity: float
    demand_tier: str


class MarginScore(TypedDict):
    """Per-product margin score."""
    id: str
    score: float
    margin_pct: float
    margin_tier: str


class CompetitionScore(TypedDict):
    """Per-product competition score."""
    id: str
    score: float
    competitor_count: int
    competition_level: str


class CompositeScore(TypedDict):
    """Per-product composite score."""
    id: str
    title: str
    composite_score: float
    demand_score: float
    margin_score: float
    competition_score: float
    tier: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ScoringOutputData(TypedDict):
    """The 'data' block of the engine output."""
    scored_products: list[CompositeScore]
    score_distribution: dict[str, int]
    avg_composite_score: float


class ScoringMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class ScoringOutput(TypedDict):
    """Final output of the product scoring engine."""
    status: str
    data: ScoringOutputData | None
    meta: ScoringMeta
    error: str | None
