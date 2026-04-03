"""Conversion Tracking Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the conversion tracking engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ConversionEvent(TypedDict, total=False):
    """Single conversion event."""
    id: str
    event_type: str
    value: float
    timestamp: str
    source: str
    customer_id: str
    session_id: str


class Touchpoint(TypedDict, total=False):
    """Single marketing touchpoint."""
    id: str
    channel: str
    campaign: str
    timestamp: str
    customer_id: str
    session_id: str
    interaction_type: str


class ConversionGoal(TypedDict, total=False):
    """A conversion goal to track against."""
    id: str
    name: str
    target_value: float
    target_count: int
    period: str


class ConversionTrackingInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    events: list[ConversionEvent]
    touchpoints: list[Touchpoint]
    goals: list[ConversionGoal]
    attribution_model: str


# ---------------------------------------------------------------------------
# Intermediate types — event tracking
# ---------------------------------------------------------------------------

class TrackedEvent(TypedDict):
    """A processed and validated conversion event."""
    id: str
    event_type: str
    value: float
    timestamp: str
    source: str
    customer_id: str
    is_valid: bool


# ---------------------------------------------------------------------------
# Intermediate types — attribution
# ---------------------------------------------------------------------------

class AttributionResult(TypedDict):
    """Attribution result for a single conversion."""
    event_id: str
    value: float
    source: str
    attribution: dict[str, float]
    model_used: str


# ---------------------------------------------------------------------------
# Intermediate types — funnel analysis
# ---------------------------------------------------------------------------

class FunnelStage(TypedDict):
    """A single stage in the conversion funnel."""
    name: str
    count: int
    rate: float
    drop_off: float


class FunnelAnalysis(TypedDict):
    """Full funnel analysis result."""
    stages: list[FunnelStage]
    overall_conversion_rate: float
    biggest_drop_off: str


# ---------------------------------------------------------------------------
# Intermediate types — goal tracking
# ---------------------------------------------------------------------------

class GoalProgress(TypedDict):
    """Progress against a conversion goal."""
    goal_id: str
    name: str
    target: float
    current: float
    progress_pct: float
    on_track: bool


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ConversionResult(TypedDict):
    """Single conversion in the output."""
    event: str
    value: float
    source: str
    attribution: dict[str, float]


class FunnelOutput(TypedDict):
    """Funnel section of the output."""
    stages: list[FunnelStage]
    drop_offs: dict[str, float]


class ConversionTrackingData(TypedDict):
    """The 'data' block of engine output."""
    conversions: list[ConversionResult]
    funnel: FunnelOutput
    goal_progress: list[GoalProgress]
    attribution_report: dict[str, float]


class ConversionTrackingMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class ConversionTrackingOutput(TypedDict):
    """Final output of the conversion tracking engine."""
    status: str
    data: ConversionTrackingData | None
    meta: ConversionTrackingMeta
    error: str | None
