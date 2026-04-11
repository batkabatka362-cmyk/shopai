"""Feedback Processing Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the feedback processing engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class FeedbackItem(TypedDict, total=False):
    """Single feedback item."""
    id: str
    content: str
    source: str
    timestamp: str
    sentiment: float
    tags: list[str]


class FeedbackInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    feedback: list[FeedbackItem]
    categories: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — categorizer
# ---------------------------------------------------------------------------

class CategorizedFeedback(TypedDict):
    """Feedback item with assigned category and theme."""
    id: str
    content: str
    category: str
    theme: str
    confidence: float


# ---------------------------------------------------------------------------
# Intermediate types — priority scorer
# ---------------------------------------------------------------------------

class PrioritizedFeedback(TypedDict):
    """Feedback item with priority score."""
    id: str
    category: str
    priority_score: float
    urgency: str
    impact: str


# ---------------------------------------------------------------------------
# Intermediate types — trend spotter
# ---------------------------------------------------------------------------

class FeedbackTrend(TypedDict):
    """A recurring theme spotted across feedback."""
    theme: str
    frequency: int
    direction: str
    examples: list[str]
    first_seen: str


# ---------------------------------------------------------------------------
# Intermediate types — action recommender
# ---------------------------------------------------------------------------

class RecommendedAction(TypedDict):
    """An action recommended based on feedback analysis."""
    action: str
    priority: str
    category: str
    supporting_feedback_count: int
    expected_impact: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class FeedbackOutputData(TypedDict):
    """The 'data' block of engine output."""
    categorized: list[CategorizedFeedback]
    priorities: list[PrioritizedFeedback]
    trends: list[FeedbackTrend]
    recommended_actions: list[RecommendedAction]


class FeedbackMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class FeedbackOutput(TypedDict):
    """Final output of the feedback processing engine."""
    status: str
    data: FeedbackOutputData | None
    meta: FeedbackMeta
    error: str | None
