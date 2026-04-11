"""Feedback Collection Engine — all TypedDicts and type aliases."""
from __future__ import annotations
from typing import Any, TypedDict

class FeedbackCollectionInputData(TypedDict, total=False):
    feedback_sources: list[dict[str, Any]]
    period: str
    filters: dict[str, Any]

class FeedbackItem(TypedDict):
    source: str
    responses: list[dict[str, Any]]

class FeedbackInsight(TypedDict):
    insight: str
    category: str
    frequency: int
    sentiment: str

class FeedbackCollectionData(TypedDict):
    feedback: list[FeedbackItem]
    insights: list[FeedbackInsight]
    sentiment_summary: dict[str, Any]
    action_items: list[str]

class FeedbackCollectionMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float

class FeedbackCollectionOutput(TypedDict):
    status: str
    data: FeedbackCollectionData | None
    meta: FeedbackCollectionMeta
    error: str | None
