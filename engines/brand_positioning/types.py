"""Brand Positioning Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the brand positioning engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class BrandInfo(TypedDict, total=False):
    """Brand information for positioning analysis."""
    name: str
    values: list[str]
    price_range: str
    quality: str


class CompetitorInfo(TypedDict, total=False):
    """Competitor information for positioning analysis."""
    name: str
    price_range: str
    quality: str
    positioning: str


class BrandPositioningInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    brand: BrandInfo
    competitors: list[CompetitorInfo]


# ---------------------------------------------------------------------------
# Intermediate types — position map
# ---------------------------------------------------------------------------

class PositionMapEntry(TypedDict):
    """Single entry on the position map."""
    name: str
    price_score: float
    quality_score: float
    quadrant: str


class PositionMap(TypedDict):
    """Position map from position_mapper."""
    entries: list[PositionMapEntry]
    brand_quadrant: str


# ---------------------------------------------------------------------------
# Intermediate types — gap analysis
# ---------------------------------------------------------------------------

class MarketGap(TypedDict):
    """Market gap from gap_analyzer."""
    quadrant: str
    description: str
    opportunity_score: float


# ---------------------------------------------------------------------------
# Intermediate types — differentiation
# ---------------------------------------------------------------------------

class DifferentiationScore(TypedDict):
    """Differentiation score from differentiation_scorer."""
    competitor_name: str
    differentiation_score: float
    shared_traits: list[str]
    unique_advantages: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — strategy
# ---------------------------------------------------------------------------

class StrategyRecommendation(TypedDict):
    """Strategy recommendation from strategy_advisor."""
    recommendation: str
    priority: str
    rationale: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class BrandPositioningData(TypedDict):
    """The 'data' block of the engine output."""
    position_map: PositionMap
    gaps: list[MarketGap]
    differentiation_scores: list[DifferentiationScore]
    strategy_recommendations: list[StrategyRecommendation]
    competitive_advantages: list[str]


class BrandPositioningMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class BrandPositioningOutput(TypedDict):
    """Final output of the brand positioning engine."""
    status: str
    data: BrandPositioningData | None
    meta: BrandPositioningMeta
    error: str | None
