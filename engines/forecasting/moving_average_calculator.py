"""Forecasting Engine — moving average calculator.

Computes Simple Moving Averages (SMA), Exponential Moving Averages (EMA),
and Weighted Moving Averages (WMA) for standard windows: 7, 30, 90 days.

Pure Python — no numpy.
"""
from __future__ import annotations

from typing import Any


def compute_moving_averages(
    cleaned_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute SMA, EMA, and WMA for 7-day, 30-day, and 90-day windows.

    Args:
        cleaned_data: List of CleanedPoint dicts (date, value).

    Returns:
        Structured dict with MovingAverageResult fields.
    """
    try:
        if not cleaned_data:
            return {
                "status": "error",
                "moving_averages": _empty_result(),
                "error": "No data for moving average calculation",
            }

        values = [p["value"] for p in cleaned_data]
        n = len(values)

        if n == 0:
            return {
                "status": "error",
                "moving_averages": _empty_result(),
                "error": "Empty values list",
            }

        # Compute all variants
        sma_7 = _sma(values, 7)
        sma_30 = _sma(values, 30)
        sma_90 = _sma(values, 90)

        ema_7 = _ema(values, 7)
        ema_30 = _ema(values, 30)
        ema_90 = _ema(values, 90)

        wma_7 = _wma(values, 7)

        return {
            "status": "success",
            "moving_averages": {
                "sma_7": [round(v, 4) for v in sma_7],
                "sma_30": [round(v, 4) for v in sma_30],
                "sma_90": [round(v, 4) for v in sma_90],
                "ema_7": [round(v, 4) for v in ema_7],
                "ema_30": [round(v, 4) for v in ema_30],
                "ema_90": [round(v, 4) for v in ema_90],
                "wma_7": [round(v, 4) for v in wma_7],
                "current_sma_7": round(sma_7[-1], 4) if sma_7 else 0.0,
                "current_ema_7": round(ema_7[-1], 4) if ema_7 else 0.0,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "moving_averages": _empty_result(),
            "error": f"Moving average calculation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Moving average implementations
# ---------------------------------------------------------------------------

def _sma(values: list[float], window: int) -> list[float]:
    """Simple Moving Average.

    SMA_t = (1/w) * sum(values[t-w+1 .. t])

    Returns a list the same length as values. The first (window-1)
    entries use an expanding window (partial SMA).
    """
    n = len(values)
    if n == 0:
        return []

    result: list[float] = []
    running_sum = 0.0

    for i in range(n):
        running_sum += values[i]
        if i >= window:
            running_sum -= values[i - window]
        actual_window = min(i + 1, window)
        result.append(running_sum / actual_window)

    return result


def _ema(values: list[float], span: int) -> list[float]:
    """Exponential Moving Average.

    EMA_t = alpha * value_t + (1 - alpha) * EMA_{t-1}
    alpha  = 2 / (span + 1)

    Returns a list the same length as values.
    """
    n = len(values)
    if n == 0:
        return []

    alpha = 2.0 / (span + 1)
    result: list[float] = [values[0]]

    for i in range(1, n):
        prev = result[-1]
        result.append(alpha * values[i] + (1.0 - alpha) * prev)

    return result


def _wma(values: list[float], window: int) -> list[float]:
    """Weighted Moving Average — linearly increasing weights.

    WMA_t = sum(w_i * v_i) / sum(w_i)   for i in [t-w+1 .. t]
    where w_i = position_in_window (1, 2, ..., w).

    Returns a list the same length as values. The first (window-1)
    entries use an expanding window.
    """
    n = len(values)
    if n == 0:
        return []

    result: list[float] = []

    for i in range(n):
        actual_window = min(i + 1, window)
        start = i - actual_window + 1
        weighted_sum = 0.0
        weight_total = 0.0

        for j in range(actual_window):
            weight = j + 1  # Linearly increasing: 1, 2, ..., w
            weighted_sum += weight * values[start + j]
            weight_total += weight

        result.append(weighted_sum / weight_total if weight_total > 0 else 0.0)

    return result


# ---------------------------------------------------------------------------
# Empty result
# ---------------------------------------------------------------------------

def _empty_result() -> dict[str, Any]:
    """Return an empty moving average result."""
    return {
        "sma_7": [],
        "sma_30": [],
        "sma_90": [],
        "ema_7": [],
        "ema_30": [],
        "ema_90": [],
        "wma_7": [],
        "current_sma_7": 0.0,
        "current_ema_7": 0.0,
    }
