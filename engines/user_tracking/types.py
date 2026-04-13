"""User Tracking Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the user tracking engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class UserTrackingInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    events: list[dict[str, Any]]
    users: list[dict[str, Any]]
    sessions: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class UserSession(TypedDict):
    """A built user session."""
    session_id: str
    user_id: str
    events: list[dict[str, Any]]
    start_time: str
    end_time: str
    duration_seconds: float


class JourneyStep(TypedDict):
    """A step in a customer journey."""
    step_number: int
    touchpoint: str
    channel: str
    timestamp: str


class Touchpoint(TypedDict):
    """An analyzed touchpoint."""
    touchpoint: str
    channel: str
    count: int
    conversion_rate: float


class AttributionResult(TypedDict):
    """Attribution for a conversion."""
    channel: str
    model: str
    attribution_pct: float
    conversions: int


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class UserTrackingData(TypedDict):
    """The 'data' block of the engine output."""
    journeys: list[dict[str, Any]]
    touchpoints: list[Touchpoint]
    attribution: list[AttributionResult]
    session_stats: dict[str, Any]


class UserTrackingMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class UserTrackingOutput(TypedDict):
    status: str
    data: UserTrackingData | None
    meta: UserTrackingMeta
    error: str | None
