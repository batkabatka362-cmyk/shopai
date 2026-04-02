"""Forecasting Engine — forecast generator.

Generates point forecasts for N periods ahead by combining:
  - Trend component (from regression)
  - Seasonality component (multiplicative seasonal indices)
  - Moving average smoothing (EMA for recent momentum)

Pure Python — no numpy.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def generate_forecast(
    cleaned_data: list[dict[str, Any]],
    trend: dict[str, Any],
    seasonality: dict[str, Any],
    regression: dict[str, Any],
    moving_averages: dict[str, Any],
    forecast_periods: int = 30,
    granularity: str = "daily",
) -> dict[str, Any]:
    """Generate point forecasts for future periods.

    Combines trend + seasonality + recent momentum to produce forecasts.

    Args:
        cleaned_data: Historical cleaned data points.
        trend: TrendResult from trend_analyzer.
        seasonality: SeasonalityResult from seasonality_detector.
        regression: RegressionResult from regression_modeler.
        moving_averages: MovingAverageResult from moving_average_calculator.
        forecast_periods: Number of periods to forecast.
        granularity: Time granularity.

    Returns:
        Structured dict with list of ForecastPoint dicts (no confidence intervals yet).
    """
    try:
        if not cleaned_data:
            return {
                "status": "error",
                "forecast": [],
                "residuals": [],
                "error": "No data for forecast generation",
            }

        values = [p["value"] for p in cleaned_data]
        n = len(values)

        if n < 2:
            return {
                "status": "error",
                "forecast": [],
                "residuals": [],
                "error": "Need at least 2 data points to forecast",
            }

        # Determine last date to start forecasting from
        last_date = _parse_date(cleaned_data[-1]["date"])
        delta = _granularity_delta(granularity)

        # Extract model components
        slope = trend.get("slope", 0.0)
        intercept = trend.get("intercept", 0.0)
        best_model = regression.get("best_model", "linear")
        poly_coeffs = regression.get("poly_coefficients", [0.0, 0.0, 0.0])

        seasonal_detected = seasonality.get("detected", False)
        seasonal_period = seasonality.get("period", 0)
        seasonal_indices = seasonality.get("seasonal_indices", [])

        # Recent momentum: use EMA-7 adjustment
        ema_7 = moving_averages.get("ema_7", [])
        momentum_adjustment = 0.0
        if ema_7 and len(ema_7) >= 2:
            # Difference between last EMA value and trend prediction at last point
            last_ema = ema_7[-1]
            last_trend = slope * (n - 1) + intercept
            momentum_adjustment = (last_ema - last_trend) * 0.3  # Damped

        # Compute in-sample residuals for confidence estimator
        residuals = _compute_residuals(
            values, n, slope, intercept, best_model, poly_coeffs,
            seasonal_detected, seasonal_period, seasonal_indices,
        )

        # Generate future forecasts
        forecast: list[dict[str, Any]] = []

        for step in range(1, forecast_periods + 1):
            future_idx = n - 1 + step
            future_date = last_date + delta * step

            # Trend component
            if best_model == "polynomial" and len(poly_coeffs) == 3:
                trend_val = (
                    poly_coeffs[0] * future_idx ** 2
                    + poly_coeffs[1] * future_idx
                    + poly_coeffs[2]
                )
            else:
                trend_val = slope * future_idx + intercept

            # Seasonality component (multiplicative)
            if seasonal_detected and seasonal_period > 0 and seasonal_indices:
                season_idx = future_idx % seasonal_period
                if season_idx < len(seasonal_indices):
                    seasonal_factor = seasonal_indices[season_idx]
                else:
                    seasonal_factor = 1.0
            else:
                seasonal_factor = 1.0

            # Combine: trend * seasonality + momentum
            predicted = trend_val * seasonal_factor + momentum_adjustment

            # Dampen momentum over time
            momentum_adjustment *= 0.95

            # Ensure non-negative for revenue/sales metrics
            predicted = max(0.0, predicted)

            forecast.append({
                "date": future_date.strftime("%Y-%m-%d"),
                "predicted": round(predicted, 2),
            })

        return {
            "status": "success",
            "forecast": forecast,
            "residuals": [round(r, 4) for r in residuals],
        }
    except Exception as exc:
        return {
            "status": "error",
            "forecast": [],
            "residuals": [],
            "error": f"Forecast generation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_residuals(
    values: list[float],
    n: int,
    slope: float,
    intercept: float,
    best_model: str,
    poly_coeffs: list[float],
    seasonal_detected: bool,
    seasonal_period: int,
    seasonal_indices: list[float],
) -> list[float]:
    """Compute in-sample residuals (actual - predicted) for error estimation."""
    residuals: list[float] = []

    for i in range(n):
        # Trend component
        if best_model == "polynomial" and len(poly_coeffs) == 3:
            trend_val = poly_coeffs[0] * i ** 2 + poly_coeffs[1] * i + poly_coeffs[2]
        else:
            trend_val = slope * i + intercept

        # Seasonality
        if seasonal_detected and seasonal_period > 0 and seasonal_indices:
            s_idx = i % seasonal_period
            if s_idx < len(seasonal_indices):
                seasonal_factor = seasonal_indices[s_idx]
            else:
                seasonal_factor = 1.0
        else:
            seasonal_factor = 1.0

        predicted = trend_val * seasonal_factor
        residuals.append(values[i] - predicted)

    return residuals


def _parse_date(date_str: str) -> datetime:
    """Parse a YYYY-MM-DD date string."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return datetime.now()


def _granularity_delta(granularity: str) -> timedelta:
    """Return the timedelta for a given granularity."""
    mapping = {
        "daily": timedelta(days=1),
        "weekly": timedelta(weeks=1),
        "monthly": timedelta(days=30),
    }
    return mapping.get(granularity, timedelta(days=1))
