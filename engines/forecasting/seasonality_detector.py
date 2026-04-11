"""Forecasting Engine — seasonality detector.

Detects seasonal patterns in time series data using autocorrelation.
Identifies weekly, monthly, quarterly, and yearly cycles and computes
seasonal indices for deseasonalizing / reseasonalizing forecasts.

Pure Python — no numpy.
"""
from __future__ import annotations

import math
from typing import Any

# Candidate periods for each granularity
_CANDIDATE_PERIODS: dict[str, list[int]] = {
    "daily": [7, 14, 30, 60, 90, 365],
    "weekly": [4, 12, 13, 26, 52],
    "monthly": [3, 6, 12],
}


def detect_seasonality(
    cleaned_data: list[dict[str, Any]],
    granularity: str = "daily",
) -> dict[str, Any]:
    """Detect seasonal patterns via autocorrelation analysis.

    Args:
        cleaned_data: List of CleanedPoint dicts (date, value).
        granularity: Time granularity — "daily", "weekly", "monthly".

    Returns:
        Structured dict with SeasonalityResult fields.
    """
    try:
        if not cleaned_data:
            return {
                "status": "error",
                "seasonality": _empty_seasonality(),
                "error": "No data for seasonality detection",
            }

        values = [p["value"] for p in cleaned_data]
        n = len(values)

        if n < 4:
            return {
                "status": "success",
                "seasonality": _empty_seasonality(),
            }

        # Compute autocorrelation at candidate lag periods
        candidates = _CANDIDATE_PERIODS.get(granularity, [7, 30, 90, 365])
        # Only test lags where we have enough data (need at least 2 full cycles)
        candidates = [p for p in candidates if p * 2 <= n]

        if not candidates:
            return {
                "status": "success",
                "seasonality": _empty_seasonality(),
            }

        peaks: list[dict[str, Any]] = []
        best_lag = 0
        best_acf = -1.0

        for lag in candidates:
            acf = _autocorrelation(values, lag)
            peaks.append({
                "lag": lag,
                "autocorrelation": round(acf, 4),
                "label": _lag_label(lag, granularity),
            })
            if acf > best_acf:
                best_acf = acf
                best_lag = lag

        # Significance threshold: 2 / sqrt(n) is a common heuristic
        significance = 2.0 / math.sqrt(n)
        detected = best_acf > significance and best_lag > 0

        # Compute seasonal indices for the detected period
        if detected:
            indices = _seasonal_indices(values, best_lag)
            amplitude = max(indices) - min(indices) if indices else 0.0
        else:
            indices = []
            amplitude = 0.0

        return {
            "status": "success",
            "seasonality": {
                "detected": detected,
                "period": best_lag,
                "amplitude": round(amplitude, 4),
                "seasonal_indices": [round(v, 4) for v in indices],
                "autocorrelation_peaks": sorted(
                    peaks, key=lambda p: p["autocorrelation"], reverse=True,
                ),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "seasonality": _empty_seasonality(),
            "error": f"Seasonality detection failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _autocorrelation(values: list[float], lag: int) -> float:
    """Compute the autocorrelation coefficient at a given lag.

    ACF(k) = cov(y_t, y_{t-k}) / var(y_t)
    """
    n = len(values)
    if lag >= n or lag <= 0:
        return 0.0

    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    if abs(variance) < 1e-12:
        return 0.0

    covariance = sum(
        (values[t] - mean) * (values[t - lag] - mean)
        for t in range(lag, n)
    ) / n

    return covariance / variance


def _seasonal_indices(values: list[float], period: int) -> list[float]:
    """Compute seasonal indices by averaging values at each position in the cycle.

    Returns a list of length `period` where each element is the average
    deviation from the global mean at that position in the cycle.
    """
    n = len(values)
    if period <= 0 or n == 0:
        return []

    global_mean = sum(values) / n
    if abs(global_mean) < 1e-12:
        global_mean = 1.0

    # Accumulate values at each position in the period
    buckets: list[list[float]] = [[] for _ in range(period)]
    for i, val in enumerate(values):
        buckets[i % period].append(val)

    # Compute average ratio at each position
    indices: list[float] = []
    for bucket in buckets:
        if bucket:
            bucket_mean = sum(bucket) / len(bucket)
            indices.append(bucket_mean / global_mean)
        else:
            indices.append(1.0)

    return indices


def _lag_label(lag: int, granularity: str) -> str:
    """Return a human-readable label for a lag period."""
    if granularity == "daily":
        labels = {7: "weekly", 14: "biweekly", 30: "monthly", 60: "bimonthly",
                  90: "quarterly", 365: "yearly"}
        return labels.get(lag, f"{lag}d")
    if granularity == "weekly":
        labels = {4: "monthly", 12: "quarterly", 13: "quarterly",
                  26: "semiannual", 52: "yearly"}
        return labels.get(lag, f"{lag}w")
    if granularity == "monthly":
        labels = {3: "quarterly", 6: "semiannual", 12: "yearly"}
        return labels.get(lag, f"{lag}m")
    return f"{lag}"


def _empty_seasonality() -> dict[str, Any]:
    """Return an empty seasonality result."""
    return {
        "detected": False,
        "period": 0,
        "amplitude": 0.0,
        "seasonal_indices": [],
        "autocorrelation_peaks": [],
    }
