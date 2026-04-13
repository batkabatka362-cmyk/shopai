"""Sentiment Analysis Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the sentiment analysis engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class TextInput(TypedDict, total=False):
    """Single text input for sentiment analysis."""
    source: str
    text: str
    date: str
    id: str
    category: str


class SentimentAnalysisInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    texts: list[TextInput]
    categories: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — text preprocessing
# ---------------------------------------------------------------------------

class ProcessedText(TypedDict):
    """Text after preprocessing."""
    id: str
    original: str
    cleaned: str
    tokens: list[str]
    source: str
    date: str


# ---------------------------------------------------------------------------
# Intermediate types — sentiment scoring
# ---------------------------------------------------------------------------

class SentimentScore(TypedDict):
    """Sentiment score for a single text."""
    id: str
    score: float
    label: str
    confidence: float
    positive_words: list[str]
    negative_words: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — topic extraction
# ---------------------------------------------------------------------------

class ExtractedTopic(TypedDict):
    """An extracted topic with its sentiment."""
    topic: str
    sentiment: float
    count: int
    representative_texts: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — trend detection
# ---------------------------------------------------------------------------

class SentimentTrend(TypedDict):
    """Sentiment trend over time."""
    period: str
    avg_sentiment: float
    volume: int
    direction: str
    change_pct: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class SentimentAlert(TypedDict):
    """Alert for significant sentiment changes."""
    type: str
    severity: str
    message: str
    topic: str
    current_sentiment: float


class SentimentDistribution(TypedDict):
    """Distribution of sentiment labels."""
    positive: int
    neutral: int
    negative: int
    positive_pct: float
    neutral_pct: float
    negative_pct: float


class SentimentAnalysisData(TypedDict):
    """The 'data' block of engine output."""
    overall_sentiment: float
    sentiment_distribution: SentimentDistribution
    topics: list[ExtractedTopic]
    trends: list[SentimentTrend]
    alerts: list[SentimentAlert]


class SentimentAnalysisMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class SentimentAnalysisOutput(TypedDict):
    """Final output of the sentiment analysis engine."""
    status: str
    data: SentimentAnalysisData | None
    meta: SentimentAnalysisMeta
    error: str | None
