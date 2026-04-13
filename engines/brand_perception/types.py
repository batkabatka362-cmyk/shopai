"""Brand Perception Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the brand perception engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class MentionItem(TypedDict, total=False):
    """Single brand mention."""
    source: str
    text: str
    date: str


class BrandPerceptionInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    brand_name: str
    mentions: list[MentionItem]
    reviews: list[dict[str, Any]]
    social_posts: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Intermediate types — mention tracking
# ---------------------------------------------------------------------------

class MentionTrackResult(TypedDict):
    """Mention tracking result from mention_tracker."""
    total_mentions: int
    by_source: dict[str, int]
    mention_texts: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — sentiment
# ---------------------------------------------------------------------------

class SentimentResult(TypedDict):
    """Sentiment aggregation from sentiment_aggregator."""
    positive_pct: float
    negative_pct: float
    neutral_pct: float
    avg_sentiment_score: float
    top_positive_themes: list[str]
    top_negative_themes: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — reputation
# ---------------------------------------------------------------------------

class ReputationResult(TypedDict):
    """Reputation score from reputation_scorer."""
    reputation_score: int
    factors: dict[str, float]


# ---------------------------------------------------------------------------
# Intermediate types — perception report
# ---------------------------------------------------------------------------

class PerceptionReport(TypedDict):
    """Perception report from perception_reporter."""
    trends: list[str]
    threats: list[str]
    opportunities: list[str]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class SentimentOutput(TypedDict):
    """Sentiment block in engine output."""
    positive_pct: float
    negative_pct: float
    neutral_pct: float


class BrandPerceptionData(TypedDict):
    """The 'data' block of the engine output."""
    mention_count: int
    sentiment: SentimentOutput
    reputation_score: int
    trends: list[str]
    threats: list[str]
    opportunities: list[str]


class BrandPerceptionMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class BrandPerceptionOutput(TypedDict):
    """Final output of the brand perception engine."""
    status: str
    data: BrandPerceptionData | None
    meta: BrandPerceptionMeta
    error: str | None
