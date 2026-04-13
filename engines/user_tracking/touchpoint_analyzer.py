"""User Tracking Engine — touchpoint analyzer.

Analyzes touchpoints across journeys: frequency, effectiveness,
conversion contribution, and channel distribution.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_touchpoints(
    journeys: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze touchpoints across all journeys.

    Args:
        journeys: Mapped customer journeys.

    Returns:
        Structured dict with touchpoint analysis.
    """
    try:
        data = copy.deepcopy(journeys)

        tp_stats: dict[str, dict[str, Any]] = {}

        for journey in data:
            converted = journey.get("converted", False)
            steps = journey.get("steps", [])

            seen_touchpoints: set[str] = set()

            for step in steps:
                tp = step.get("touchpoint", "unknown")
                channel = step.get("channel", "unknown")
                key = f"{tp}|{channel}"

                if key not in tp_stats:
                    tp_stats[key] = {
                        "touchpoint": tp,
                        "channel": channel,
                        "count": 0,
                        "journeys_with": 0,
                        "conversions_with": 0,
                    }

                tp_stats[key]["count"] += 1

                if key not in seen_touchpoints:
                    seen_touchpoints.add(key)
                    tp_stats[key]["journeys_with"] += 1
                    if converted:
                        tp_stats[key]["conversions_with"] += 1

        touchpoints: list[dict[str, Any]] = []
        for stats in tp_stats.values():
            jw = stats["journeys_with"]
            cw = stats["conversions_with"]
            conversion_rate = round(cw / jw * 100, 1) if jw > 0 else 0.0

            touchpoints.append({
                "touchpoint": stats["touchpoint"],
                "channel": stats["channel"],
                "count": stats["count"],
                "conversion_rate": conversion_rate,
            })

        touchpoints.sort(key=lambda t: t["count"], reverse=True)

        return {
            "status": "success",
            "touchpoints": touchpoints,
            "total_touchpoints": len(touchpoints),
        }
    except Exception as exc:
        return {
            "status": "error",
            "touchpoints": [],
            "error": f"Touchpoint analysis failed: {exc}",
        }
