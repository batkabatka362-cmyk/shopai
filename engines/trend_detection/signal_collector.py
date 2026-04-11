"""Trend Detection Engine — signal collector.

Collects and aggregates raw data signals per trend name, computing
signal strength and basic statistics.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def collect_signals(
    data_points: list[dict[str, Any]],
    categories: list[dict[str, Any]],
) -> dict[str, Any]:
    """Collect signals for each trend.

    Args:
        data_points: List of data point dicts.
        categories: List of category info dicts.

    Returns:
        Structured dict with per-trend signal results.
    """
    try:
        # Group data points by name
        groups: dict[str, list[dict[str, Any]]] = {}
        for dp in data_points:
            name = str(dp.get("name", "unknown"))
            groups.setdefault(name, []).append(dp)

        # Category weight map
        cat_weights: dict[str, float] = {}
        for cat in categories:
            cat_weights[str(cat.get("name", ""))] = float(cat.get("weight", 1.0))

        signals: list[dict[str, Any]] = []

        for name, points in groups.items():
            points.sort(key=lambda p: str(p.get("period", "")))

            values = [float(p.get("value", 0.0)) for p in points]
            category = str(points[0].get("category", "")) if points else ""

            if not values:
                continue

            earliest = values[0]
            latest = values[-1]
            n = len(values)

            # Signal strength: magnitude of change relative to initial value
            if earliest != 0:
                pct_change = abs(latest - earliest) / abs(earliest)
            else:
                pct_change = abs(latest)

            cat_weight = cat_weights.get(category, 1.0)
            signal_strength = round(min(pct_change * cat_weight, 1.0), 3)

            signals.append({
                "name": name,
                "category": category,
                "signal_strength": signal_strength,
                "data_points_count": n,
                "latest_value": round(latest, 4),
                "earliest_value": round(earliest, 4),
            })

        return {"status": "success", "signals": signals}
    except Exception as exc:
        return {"status": "error", "signals": [], "error": f"Signal collection failed: {exc}"}
