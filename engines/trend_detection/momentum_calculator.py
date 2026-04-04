"""Trend Detection Engine — momentum calculator.

Calculates trend momentum, direction, acceleration, and consistency
from time-series data points.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def calculate_momentum(
    data_points: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate momentum for each trend.

    Args:
        data_points: List of data point dicts.
        signals: Per-trend signal results.

    Returns:
        Structured dict with per-trend momentum results.
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

            if n < 2:
                results.append({
                    "name": name,
                    "momentum": 0.0,
                    "direction": "flat",
                    "acceleration": 0.0,
                    "consistency": 0.0,
                })
                continue

            # Calculate period-over-period changes
            changes = [values[i] - values[i - 1] for i in range(1, n)]

            # Momentum: average rate of change
            momentum = round(sum(changes) / len(changes), 4)

            # Direction
            if momentum > 0.01:
                direction = "rising"
            elif momentum < -0.01:
                direction = "falling"
            else:
                direction = "flat"

            # Acceleration: change in rate of change
            if len(changes) >= 2:
                accels = [changes[i] - changes[i - 1] for i in range(1, len(changes))]
                acceleration = round(sum(accels) / len(accels), 4)
            else:
                acceleration = 0.0

            # Consistency: what fraction of periods agree with overall direction
            if momentum > 0:
                consistent = sum(1 for c in changes if c > 0)
            elif momentum < 0:
                consistent = sum(1 for c in changes if c < 0)
            else:
                consistent = sum(1 for c in changes if abs(c) < 0.01)

            consistency = round(consistent / len(changes), 3) if changes else 0.0

            results.append({
                "name": name,
                "momentum": momentum,
                "direction": direction,
                "acceleration": acceleration,
                "consistency": consistency,
            })

        return {"status": "success", "momentums": results}
    except Exception as exc:
        return {"status": "error", "momentums": [], "error": f"Momentum calculation failed: {exc}"}
