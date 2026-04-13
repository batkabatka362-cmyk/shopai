"""Event Tracking Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the event tracking engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class EventTrackingInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    events: list[dict[str, Any]]
    period: str


# ---------------------------------------------------------------------------
# Intermediate types — event collection
# ---------------------------------------------------------------------------

class EventGroup(TypedDict):
    """Events grouped by type."""
    event_type: str
    events: list[dict[str, Any]]
    count: int


# ---------------------------------------------------------------------------
# Intermediate types — event categorization
# ---------------------------------------------------------------------------

class CategorizedEvent(TypedDict):
    """An event with its category assignment."""
    event_type: str
    category: str
    subcategory: str
    count: int
    priority: str


# ---------------------------------------------------------------------------
# Intermediate types — metric aggregation
# ---------------------------------------------------------------------------

class EventMetric(TypedDict):
    """Aggregated metric for an event type."""
    metric_name: str
    value: float
    unit: str
    trend: str


# ---------------------------------------------------------------------------
# Intermediate types — anomaly detection
# ---------------------------------------------------------------------------

class EventAnomaly(TypedDict):
    """A detected anomaly in event patterns."""
    event_type: str
    anomaly_type: str
    severity: str
    expected_value: float
    actual_value: float
    deviation_pct: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class EventTrackingData(TypedDict):
    """The 'data' block of the engine output."""
    event_summary: dict[str, Any]
    metrics: list[EventMetric]
    anomalies: list[EventAnomaly]
    trends: list[dict[str, Any]]


class EventTrackingMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class EventTrackingOutput(TypedDict):
    """Final output of the event tracking engine."""
    status: str
    data: EventTrackingData | None
    meta: EventTrackingMeta
    error: str | None
