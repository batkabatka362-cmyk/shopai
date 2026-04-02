"""Review Management Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the review management engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ReviewItem(TypedDict, total=False):
    """A single product review."""
    id: str
    rating: float
    text: str
    date: str
    verified: bool
    helpful_votes: int


class ReviewInputData(TypedDict, total=False):
    """The 'data' block of the engine input."""
    product_id: str
    reviews: list[ReviewItem]


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class ReviewSummary(TypedDict):
    """Aggregated review summary from review_aggregator."""
    avg_rating: float
    total_reviews: int
    rating_distribution: dict[str, int]
    verified_count: int
    unverified_count: int
    avg_helpful_votes: float


class SentimentResult(TypedDict):
    """Per-review sentiment from sentiment_analyzer."""
    review_id: str
    sentiment: str          # positive | negative | neutral | mixed
    score: float            # -1.0 to 1.0
    positive_words: list[str]
    negative_words: list[str]


class SentimentSummary(TypedDict):
    """Aggregate sentiment across all reviews."""
    positive_pct: float
    negative_pct: float
    neutral_pct: float
    mixed_pct: float
    avg_score: float
    per_review: list[SentimentResult]


class TopicResult(TypedDict):
    """Extracted topic with frequency count."""
    topic: str
    frequency: int
    sentiment_avg: float
    sample_snippets: list[str]


class RatingTrend(TypedDict):
    """Rating trend analysis from rating_analyzer."""
    direction: str          # improving | declining | stable
    recent_avg: float
    overall_avg: float
    moving_averages: list[float]
    velocity: float
    model_note: str


class ReviewResponse(TypedDict):
    """Generated response for a single review."""
    review_id: str
    rating: float
    tone: str
    response_text: str
    model_note: str


class InsightItem(TypedDict):
    """A single actionable insight from insight_extractor."""
    category: str           # praise | complaint | expectation
    description: str
    frequency: int
    avg_rating_impact: float
    sample_reviews: list[str]


class ImprovementItem(TypedDict):
    """A single improvement suggestion from improvement_suggester."""
    area: str
    suggestion: str
    priority: str           # high | medium | low
    estimated_impact: float
    source_insight: str
    model_note: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ReviewManagementOutput(TypedDict):
    """Final output of the review management engine."""
    status: str
    data: ReviewManagementData | None
    meta: ReviewManagementMeta
    error: str | None


class ReviewManagementData(TypedDict):
    """The 'data' block of the engine output."""
    summary: dict[str, Any]
    sentiment: dict[str, Any]
    topics: list[dict[str, Any]]
    trend: dict[str, Any]
    responses: list[dict[str, Any]]
    insights: list[dict[str, Any]]
    improvements: list[dict[str, Any]]
    confidence: float


class ReviewManagementMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
