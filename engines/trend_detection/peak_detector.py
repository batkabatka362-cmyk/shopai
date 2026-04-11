"""Trend Detection Engine — peak detector.

Detects whether each trend is at a peak, trough, or between,
based on recent data trajectory.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def detect_peaks(
    data_points: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Detect peaks and troughs for each trend.

    Args:
        data_points: List of data point dicts.
        signals: Per-trend signal results.

    Returns:
        Structured dict with per-trend peak detection results.
    """
    try:
        groups: dict[str, list[dict[str, Any]]] = {}
        for dp in data_points:
            name = str(dp.get("name", "unknown"))
            groups.setdefault(name, []).append(dp)

        results: list[dict[str, Any]] = []

        for signal in signals:
            name = str(signal.get("name", "unknown"))
            points = groups.get(name, [])
            points.sort(key=lambda p: str(p.get("period", "")))

            values = [float(p.get("value", 0.0)) for p in points]
            n = len(values)

            if n < 3:
                results.append({
                    "name": name,
                    "is_at_peak": False,
                    "is_at_trough": False,
                    "peak_value": max(values) if values else 0.0,
                    "trough_value": min(values) if values else 0.0,
                    "current_position": "insufficient_data",
                })
                continue

            peak_value = max(values)
            trough_value = min(values)
            current = values[-1]
            prev = values[-2]
            prev2 = values[-3]

            # Peak: previous was higher than both neighbors
            is_at_peak = prev > prev2 and prev > current and current == peak_value or current >= peak_value * 0.98
            # Trough: previous was lower than both neighbors
            is_at_trough = prev < prev2 and prev < current and current == trough_value or current <= trough_value * 1.02

            # Current position
            if is_at_peak:
                position = "at_peak"
            elif is_at_trough:
                position = "at_trough"
            elif current > prev:
                position = "ascending"
            elif current < prev:
                position = "descending"
            else:
                position = "plateau"

            results.append({
                "name": name,
                "is_at_peak": is_at_peak,
                "is_at_trough": is_at_trough,
                "peak_value": round(peak_value, 4),
                "trough_value": round(trough_value, 4),
                "current_position": position,
            })

        return {"status": "success", "peaks": results}
    except Exception as exc:
        return {"status": "error", "peaks": [], "error": f"Peak detection failed: {exc}"}
