"""Learning Loop — all TypedDicts and type aliases.

Single source of truth for every data shape in the learning loop engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class LearningLoopInput(TypedDict, total=False):
    """Raw input payload arriving at the engine."""
    status: str
    data: LearningLoopInputData
    meta: dict[str, Any]
    error: str | None


class LearningLoopInputData(TypedDict, total=False):
    """The 'data' block inside the input payload."""
    task: str
    decision: str
    execution: str
    result: ExecutionResult


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------

class ExecutionResult(TypedDict, total=False):
    """Raw metrics from an executed action."""
    views: int
    clicks: int
    sales: int
    revenue: float
    cost: float
    bounce_rate: float
    conversion_rate: float
    impressions: int
    engagements: int
    orders: int
    returns: int
    sessions: int


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

class EvaluationResult(TypedDict):
    """Output of the evaluator stage."""
    performance: str
    score: float
    metrics: dict[str, float]
    benchmarks: dict[str, float]
    deviations: dict[str, float]
    model_note: str


# ---------------------------------------------------------------------------
# Error detection
# ---------------------------------------------------------------------------

class ErrorInfo(TypedDict):
    """A single detected error or anomaly."""
    type: str
    severity: str
    detail: str
    metric: str
    actual: float
    threshold: float


# ---------------------------------------------------------------------------
# Pattern analysis
# ---------------------------------------------------------------------------

class PatternInfo(TypedDict):
    """A single detected recurring pattern."""
    type: str
    detail: str
    frequency: int
    confidence: float
    supporting_records: int


# ---------------------------------------------------------------------------
# Insight generation
# ---------------------------------------------------------------------------

class InsightInfo(TypedDict):
    """A single actionable insight."""
    insight: str
    source: str
    priority: str
    confidence: float


# ---------------------------------------------------------------------------
# Improvement suggestion
# ---------------------------------------------------------------------------

class ImprovementSuggestion(TypedDict):
    """A concrete improvement suggestion."""
    action: str
    expected_impact: str
    priority: str
    confidence: float
    rationale: str


# ---------------------------------------------------------------------------
# Feedback payload
# ---------------------------------------------------------------------------

class FeedbackPayload(TypedDict):
    """Structured feedback for the decision system."""
    source_task: str
    source_decision: str
    performance_label: str
    errors: list[ErrorInfo]
    top_improvements: list[ImprovementSuggestion]
    confidence: float
    timestamp: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class LearningLoopOutput(TypedDict):
    """Final output of the learning loop engine."""
    status: str
    data: LearningLoopData | None
    meta: LearningLoopMeta
    error: str | None


class LearningLoopData(TypedDict):
    """The 'data' block of the engine output."""
    performance: str
    errors: list[ErrorInfo]
    patterns: list[PatternInfo]
    insights: list[InsightInfo]
    improvements: list[ImprovementSuggestion]
    feedback: FeedbackPayload
    confidence: float


class LearningLoopMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


# ---------------------------------------------------------------------------
# Memory record
# ---------------------------------------------------------------------------

class LearningRecord(TypedDict, total=False):
    """A stored learning record."""
    record_id: str
    timestamp: str
    task: str
    decision: str
    execution: str
    result: dict[str, Any]
    performance: str
    score: float
    errors: list[ErrorInfo]
    patterns: list[PatternInfo]
    insights: list[InsightInfo]
    improvements: list[ImprovementSuggestion]
    confidence: float
