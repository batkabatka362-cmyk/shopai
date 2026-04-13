"""Forecasting Engine — confidence estimator.

Estimates confidence intervals (80% and 95%) for forecast points using
historical forecast errors (residuals) and residual analysis.

Intervals widen over the forecast horizon to reflect increasing uncertainty.

Pure Python — no numpy.
"""
from __future__ import annotations

import math
from typing import Any

# Z-scores for confidence levels (normal distribution approximation)
_Z_80 = 1.2816  # ~80% CI
_Z_95 = 1.9600  # ~95% CI


def estimate_confidence(
    forecast: list[dict[str, Any]],
    residuals: list[float],
    cleaned_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Add confidence intervals to forecast points and compute overall confidence.

    Args:
        forecast: List of {date, predicted} dicts from forecast_generator.
        residuals: In-sample residuals from forecast_generator.
        cleaned_data: Historical cleaned data for context.

    Returns:
        Structured dict with updated forecast (incl. intervals) and model accuracy.
    """
    try:
        if not forecast:
            return {
                "status": "error",
                "forecast_with_ci": [],
                "model_accuracy": _empty_accuracy(),
                "overall_confidence": 0.0,
                "error": "No forecast points to estimate confidence for",
            }

        if not residuals:
            # No residuals — return wide default intervals
            return _default_intervals(forecast)

        # ---- Compute residual statistics ----
        n_res = len(residuals)
        mean_res = sum(residuals) / n_res
        variance = sum((r - mean_res) ** 2 for r in residuals) / max(n_res - 1, 1)
        std_res = math.sqrt(variance)

        # ---- Compute model accuracy metrics ----
        values = [p["value"] for p in cleaned_data] if cleaned_data else []
        accuracy = _compute_accuracy(residuals, values)

        # ---- Build confidence intervals ----
        forecast_with_ci: list[dict[str, Any]] = []

        for step_idx, point in enumerate(forecast):
            predicted = point["predicted"]
            step = step_idx + 1

            # Interval width grows with sqrt(step) — uncertainty fan
            horizon_factor = math.sqrt(step)
            se = std_res * horizon_factor

            lower_80 = max(0.0, predicted - _Z_80 * se)
            upper_80 = predicted + _Z_80 * se
            lower_95 = max(0.0, predicted - _Z_95 * se)
            upper_95 = predicted + _Z_95 * se

            forecast_with_ci.append({
                "date": point["date"],
                "predicted": round(predicted, 2),
                "lower_80": round(lower_80, 2),
                "upper_80": round(upper_80, 2),
                "lower_95": round(lower_95, 2),
                "upper_95": round(upper_95, 2),
            })

        # ---- Overall confidence score (0..1) ----
        # Based on R-squared, normalized residual std, and data quantity
        overall = _compute_overall_confidence(
            r_squared=accuracy["r_squared"],
            std_res=std_res,
            mean_value=sum(values) / len(values) if values else 1.0,
            n_points=len(values),
        )

        return {
            "status": "success",
            "forecast_with_ci": forecast_with_ci,
            "model_accuracy": accuracy,
            "overall_confidence": round(overall, 4),
        }
    except Exception as exc:
        return {
            "status": "error",
            "forecast_with_ci": [],
            "model_accuracy": _empty_accuracy(),
            "overall_confidence": 0.0,
            "error": f"Confidence estimation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Model accuracy metrics
# ---------------------------------------------------------------------------

def _compute_accuracy(
    residuals: list[float],
    actual_values: list[float],
) -> dict[str, Any]:
    """Compute MAE, RMSE, MAPE, and R-squared from residuals."""
    n = len(residuals)
    if n == 0:
        return _empty_accuracy()

    # MAE — Mean Absolute Error
    mae = sum(abs(r) for r in residuals) / n

    # RMSE — Root Mean Squared Error
    mse = sum(r ** 2 for r in residuals) / n
    rmse = math.sqrt(mse)

    # MAPE — Mean Absolute Percentage Error
    if actual_values and len(actual_values) == n:
        ape_sum = 0.0
        ape_count = 0
        for i in range(n):
            if abs(actual_values[i]) > 1e-8:
                ape_sum += abs(residuals[i]) / abs(actual_values[i])
                ape_count += 1
        mape = (ape_sum / ape_count * 100.0) if ape_count > 0 else 0.0
    else:
        mape = 0.0

    # R-squared from residuals
    if actual_values and len(actual_values) == n:
        mean_y = sum(actual_values) / n
        ss_tot = sum((y - mean_y) ** 2 for y in actual_values)
        ss_res = sum(r ** 2 for r in residuals)
        r_sq = max(0.0, 1.0 - ss_res / ss_tot) if abs(ss_tot) > 1e-12 else 1.0
    else:
        r_sq = 0.0

    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "mape": round(mape, 2),
        "r_squared": round(r_sq, 4),
    }


def _compute_overall_confidence(
    r_squared: float,
    std_res: float,
    mean_value: float,
    n_points: int,
) -> float:
    """Compute a composite confidence score in [0, 1].

    Factors:
      - R-squared: higher is better (40% weight)
      - Coefficient of variation of residuals: lower is better (30% weight)
      - Data quantity: more data = more confident (30% weight)
    """
    # R-squared component
    r2_score = max(0.0, min(1.0, r_squared))

    # CV component: std_res / mean_value — lower = better
    if abs(mean_value) > 1e-8:
        cv = std_res / abs(mean_value)
        cv_score = max(0.0, 1.0 - min(cv, 1.0))
    else:
        cv_score = 0.5

    # Data quantity component: asymptotic — 30 points = ~0.7, 90 = ~0.9
    qty_score = 1.0 - math.exp(-n_points / 60.0)

    return 0.4 * r2_score + 0.3 * cv_score + 0.3 * qty_score


# ---------------------------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------------------------

def _default_intervals(
    forecast: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return forecast with wide default intervals when no residuals available."""
    forecast_with_ci: list[dict[str, Any]] = []
    for point in forecast:
        predicted = point["predicted"]
        # Use 20% of predicted value as default spread
        spread = abs(predicted) * 0.2
        forecast_with_ci.append({
            "date": point["date"],
            "predicted": round(predicted, 2),
            "lower_80": round(max(0.0, predicted - spread), 2),
            "upper_80": round(predicted + spread, 2),
            "lower_95": round(max(0.0, predicted - spread * 1.5), 2),
            "upper_95": round(predicted + spread * 1.5, 2),
        })

    return {
        "status": "success",
        "forecast_with_ci": forecast_with_ci,
        "model_accuracy": _empty_accuracy(),
        "overall_confidence": 0.3,
    }


def _empty_accuracy() -> dict[str, Any]:
    """Return empty accuracy metrics."""
    return {
        "mae": 0.0,
        "rmse": 0.0,
        "mape": 0.0,
        "r_squared": 0.0,
    }
