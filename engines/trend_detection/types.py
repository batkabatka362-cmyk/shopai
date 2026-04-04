"""Trend Detection Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the trend detection engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class DataPoint(TypedDict, total=False):
    """Single data point for trend analysis."""
    name: str
    category: str
    period: str
    value: float
    source: str


class CategoryInfo(TypedDict, total=False):
    """Category metadata."""
    name: str
    parent: str
    weight: float


class TrendInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    data_points: list[DataPoint]
    categories: list[CategoryInfo]


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class SignalResult(TypedDict):
    """Per-trend signal from signal_collector."""
    name: str
    category: str
    signal_strength: float
    data_points_count: int
    latest_value: float
    earliest_value: float


class MomentumResult(TypedDict):
    """Per-trend momentum from momentum_calculator."""
    name: str
    momentum: float
    direction: str
    acceleration: float
    consistency: float


class PeakResult(TypedDict):
    """Per-trend peak detection from peak_detector."""
    name: str
    is_at_peak: bool
    is_at_trough: bool
    peak_value: float
    trough_value: float
    current_position: str


class ForecastResult(TypedDict):
    """Per-trend forecast from forecast_builder."""
    name: str
    forecast_next_period: float
    forecast_3_periods: float
    confidence: float
    trend_continuation_probability: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class TrendItem(TypedDict):
    """Single trend in output."""
    name: str
    direction: str
    momentum: float
    confidence: float
    forecast_next: float


class TrendData(TypedDict):
    """The 'data' block of the engine output."""
    trends: list[TrendItem]


class TrendMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class TrendOutput(TypedDict):
    """Final output of the trend detection engine."""
    status: str
    data: TrendData | None
    meta: TrendMeta
    error: str | None
