"""Behavioral Data Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the behavioral data engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class BehavioralDataInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    sessions: list[dict[str, Any]]
    events: list[dict[str, Any]]
    product_views: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Intermediate types — click tracking
# ---------------------------------------------------------------------------

class ClickSummary(TypedDict):
    """Aggregated click/view data for a product."""
    product_id: str
    clicks: int
    views: int
    click_through_rate: float


# ---------------------------------------------------------------------------
# Intermediate types — session analysis
# ---------------------------------------------------------------------------

class SessionPattern(TypedDict):
    """Analyzed session pattern."""
    session_id: str
    duration_seconds: float
    pages_viewed: int
    bounce: bool
    conversion: bool


# ---------------------------------------------------------------------------
# Intermediate types — engagement scoring
# ---------------------------------------------------------------------------

class EngagementScore(TypedDict):
    """Engagement score for a user/session."""
    entity_id: str
    score: float
    level: str
    factors: dict[str, float]


# ---------------------------------------------------------------------------
# Intermediate types — heatmap
# ---------------------------------------------------------------------------

class HeatmapCell(TypedDict):
    """A single cell in the interaction heatmap."""
    element: str
    interaction_count: int
    intensity: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class BehavioralDataData(TypedDict):
    """The 'data' block of the engine output."""
    behavior_summary: dict[str, Any]
    engagement_scores: list[EngagementScore]
    heatmaps: list[HeatmapCell]
    top_products: list[dict[str, Any]]


class BehavioralDataMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class BehavioralDataOutput(TypedDict):
    """Final output of the behavioral data engine."""
    status: str
    data: BehavioralDataData | None
    meta: BehavioralDataMeta
    error: str | None
