"""Forecasting Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the forecasting engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class HistoryPoint(TypedDict):
    """A single historical data point."""
    date: str
    value: float


class ForecastInputData(TypedDict, total=False):
    """The 'data' block of the engine input."""
    metric: str
    history: list[HistoryPoint]
    forecast_periods: int
    granularity: str


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

class CleanedPoint(TypedDict):
    """A data point after preprocessing — outlier flags and normalization."""
    date: str
    value: float
    original_value: float
    is_interpolated: bool
    is_outlier: bool


class TrendResult(TypedDict):
    """Trend analysis output."""
    direction: str
    strength: float
    slope: float
    intercept: float
    trend_changes: list[dict[str, Any]]
    model_note: str


class SeasonalityResult(TypedDict):
    """Seasonality detection output."""
    detected: bool
    period: int
    amplitude: float
    seasonal_indices: list[float]
    autocorrelation_peaks: list[dict[str, Any]]


class MovingAverageResult(TypedDict):
    """Moving average calculation output."""
    sma_7: list[float]
    sma_30: list[float]
    sma_90: list[float]
    ema_7: list[float]
    ema_30: list[float]
    ema_90: list[float]
    wma_7: list[float]
    current_sma_7: float
    current_ema_7: float


class RegressionResult(TypedDict):
    """Regression modeling output."""
    linear_slope: float
    linear_intercept: float
    linear_r_squared: float
    poly_coefficients: list[float]
    poly_r_squared: float
    best_model: str
    model_note: str


class ForecastPoint(TypedDict):
    """A single forecast point with confidence intervals."""
    date: str
    predicted: float
    lower_80: float
    upper_80: float
    lower_95: float
    upper_95: float


class ModelAccuracy(TypedDict):
    """Model accuracy metrics computed via backtest."""
    mae: float
    rmse: float
    mape: float
    r_squared: float


class ScenarioForecast(TypedDict):
    """A single scenario forecast point."""
    date: str
    predicted: float


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class ForecastingData(TypedDict):
    """The 'data' block of the engine output."""
    forecast: list[ForecastPoint]
    trend: TrendResult
    seasonality: SeasonalityResult
    scenarios: dict[str, list[ScenarioForecast]]
    model_accuracy: ModelAccuracy
    confidence: float


class ForecastingMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float
    metric: str
    history_points: int
    forecast_periods: int
    granularity: str


class ForecastingOutput(TypedDict):
    """Final output of the forecasting engine."""
    status: str
    data: ForecastingData | None
    meta: ForecastingMeta
    error: str | None
