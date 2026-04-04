"""Trend Detection Engine — forecast builder.

Builds short-term forecasts for each trend using linear projection
and momentum data.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def build_forecasts(
    data_points: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    momentums: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build forecasts for each trend.

    Args:
        data_points: List of data point dicts.
        signals: Per-trend signal results.
        momentums: Per-trend momentum results.

    Returns:
        Structured dict with per-trend forecast results.
    """
    try:
        groups: dict[str, list[dict[str, Any]]] = {}
        for dp in data_points:
            name = str(dp.get("name", "unknown"))
            groups.setdefault(name, []).append(dp)

        mom_map = {str(m.get("name", "")): m for m in momentums}

        forecasts: list[dict[str, Any]] = []

        for signal in signals:
            name = str(signal.get("name", "unknown"))
            points = groups.get(name, [])
            points.sort(key=lambda p: str(p.get("period", "")))

            values = [float(p.get("value", 0.0)) for p in points]
            mom = mom_map.get(name, {})
            momentum = float(mom.get("momentum", 0.0))
            consistency = float(mom.get("consistency", 0.0))
            n = len(values)

            if n == 0:
                forecasts.append({
                    "name": name,
                    "forecast_next_period": 0.0,
                    "forecast_3_periods": 0.0,
                    "confidence": 0.0,
                    "trend_continuation_probability": 0.0,
                })
                continue

            current = values[-1]

            # Simple linear projection using momentum
            forecast_1 = round(current + momentum, 4)
            forecast_3 = round(current + momentum * 3, 4)

            # Confidence based on data quantity and consistency
            data_confidence = min(n / 10.0, 1.0)
            confidence = round(data_confidence * 0.5 + consistency * 0.5, 3)

            # Trend continuation probability
            if consistency > 0.7 and abs(momentum) > 0.01:
                continuation = round(0.5 + consistency * 0.4, 3)
            elif consistency > 0.5:
                continuation = round(0.3 + consistency * 0.3, 3)
            else:
                continuation = round(max(0.2, consistency * 0.5), 3)

            forecasts.append({
                "name": name,
                "forecast_next_period": forecast_1,
                "forecast_3_periods": forecast_3,
                "confidence": confidence,
                "trend_continuation_probability": continuation,
            })

        return {"status": "success", "forecasts": forecasts}
    except Exception as exc:
        return {"status": "error", "forecasts": [], "error": f"Forecast building failed: {exc}"}
