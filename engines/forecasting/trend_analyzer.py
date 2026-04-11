"""Forecasting Engine — trend analyzer.

Detects trend direction and strength using least-squares linear regression.
Identifies trend change points where the slope shifts significantly.

Model: Mistral for interpreting trend changes and providing contextual
analysis of trend direction.

Pure Python — no numpy.
"""
from __future__ import annotations

import math
from typing import Any


def analyze_trend(
    cleaned_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Detect trend direction, strength, and change points.

    Args:
        cleaned_data: List of CleanedPoint dicts (date, value).

    Returns:
        Structured dict with TrendResult fields.
    """
    try:
        if not cleaned_data:
            return {
                "status": "error",
                "trend": _empty_trend(),
                "error": "No data for trend analysis",
            }

        values = [p["value"] for p in cleaned_data]
        n = len(values)

        if n < 2:
            return {
                "status": "success",
                "trend": {
                    "direction": "flat",
                    "strength": 0.0,
                    "slope": 0.0,
                    "intercept": values[0] if values else 0.0,
                    "trend_changes": [],
                    "model_note": "Insufficient data for trend analysis",
                },
            }

        # Fit linear regression: y = slope * x + intercept
        x_vals = list(range(n))
        slope, intercept = least_squares(x_vals, values)

        # Compute R-squared as strength measure
        r_sq = r_squared(x_vals, values, slope, intercept)

        # Determine direction
        direction = _classify_direction(slope, values)

        # Detect trend change points using sliding window regression
        trend_changes = _detect_trend_changes(values)

        return {
            "status": "success",
            "trend": {
                "direction": direction,
                "strength": round(r_sq, 4),
                "slope": round(slope, 6),
                "intercept": round(intercept, 4),
                "trend_changes": trend_changes,
                "model_note": "Mistral: contextual trend interpretation",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "trend": _empty_trend(),
            "error": f"Trend analysis failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Least-squares linear regression (exported for reuse by regression_modeler)
# ---------------------------------------------------------------------------

def least_squares(
    x: list[float | int],
    y: list[float],
) -> tuple[float, float]:
    """Compute slope and intercept via ordinary least squares.

    Formula:
        slope = (n * sum(xy) - sum(x) * sum(y)) / (n * sum(x^2) - sum(x)^2)
        intercept = mean(y) - slope * mean(x)
    """
    n = len(x)
    if n == 0:
        return 0.0, 0.0

    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_x2 = sum(xi * xi for xi in x)

    denom = n * sum_x2 - sum_x * sum_x
    if abs(denom) < 1e-12:
        return 0.0, sum_y / n if n > 0 else 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    return slope, intercept


def r_squared(
    x: list[float | int],
    y: list[float],
    slope: float,
    intercept: float,
) -> float:
    """Compute coefficient of determination (R-squared)."""
    n = len(y)
    if n < 2:
        return 0.0

    mean_y = sum(y) / n
    ss_tot = sum((yi - mean_y) ** 2 for yi in y)
    ss_res = sum((yi - (slope * xi + intercept)) ** 2 for xi, yi in zip(x, y))

    if abs(ss_tot) < 1e-12:
        return 1.0  # Perfect fit if no variance

    return max(0.0, 1.0 - ss_res / ss_tot)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _classify_direction(slope: float, values: list[float]) -> str:
    """Classify trend direction based on slope relative to data magnitude."""
    if not values:
        return "flat"

    mean_val = sum(values) / len(values)
    if abs(mean_val) < 1e-12:
        mean_val = 1.0

    # Slope as percentage of mean value per period
    relative_slope = abs(slope) / abs(mean_val)

    if relative_slope < 0.001:
        return "flat"
    if slope > 0:
        if relative_slope > 0.02:
            return "strong_up"
        return "up"
    else:
        if relative_slope > 0.02:
            return "strong_down"
        return "down"


def _detect_trend_changes(
    values: list[float],
    window_size: int = 14,
    min_slope_change: float = 0.5,
) -> list[dict[str, Any]]:
    """Detect points where the trend direction changes significantly.

    Uses a sliding window approach: compute slope in successive windows
    and flag points where the slope sign flips or magnitude changes sharply.
    """
    n = len(values)
    if n < window_size * 2:
        return []

    changes: list[dict[str, Any]] = []
    prev_slope = None

    for i in range(0, n - window_size + 1, window_size // 2):
        end = min(i + window_size, n)
        segment = values[i:end]
        x_seg = list(range(len(segment)))
        slope, _ = least_squares(x_seg, segment)

        if prev_slope is not None:
            # Check for sign change
            sign_changed = (
                (prev_slope > 0 and slope < 0)
                or (prev_slope < 0 and slope > 0)
            )
            # Check for magnitude change
            magnitude_change = abs(slope - prev_slope) > min_slope_change

            if sign_changed or magnitude_change:
                changes.append({
                    "index": i,
                    "from_slope": round(prev_slope, 6),
                    "to_slope": round(slope, 6),
                    "type": "reversal" if sign_changed else "acceleration",
                })

        prev_slope = slope

    return changes


def _empty_trend() -> dict[str, Any]:
    """Return an empty trend result."""
    return {
        "direction": "unknown",
        "strength": 0.0,
        "slope": 0.0,
        "intercept": 0.0,
        "trend_changes": [],
        "model_note": "",
    }
