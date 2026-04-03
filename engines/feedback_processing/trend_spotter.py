"""Feedback Processing Engine — trend spotter.

Spots recurring themes across categorized feedback items by counting
theme frequencies and detecting direction.
"""
from __future__ import annotations

import copy
from typing import Any


_MIN_FREQUENCY = 2


def spot_trends(
    categorized: list[dict[str, Any]],
    feedback: list[dict[str, Any]],
) -> dict[str, Any]:
    """Spot recurring themes and trends in feedback.

    Args:
        categorized: Output from categorizer.
        feedback: Original feedback items (for timestamps).

    Returns:
        Structured dict with spotted trends.
    """
    try:
        items = copy.deepcopy(categorized)
        ts_map: dict[str, str] = {}
        for fb in feedback:
            ts_map[str(fb.get("id", ""))] = str(fb.get("timestamp", ""))

        # Group by theme
        theme_data: dict[str, dict[str, Any]] = {}
        for item in items:
            theme = str(item.get("theme", "general"))
            if theme not in theme_data:
                theme_data[theme] = {
                    "frequency": 0,
                    "examples": [],
                    "timestamps": [],
                    "categories": [],
                }
            theme_data[theme]["frequency"] += 1
            content = str(item.get("content", ""))
            if len(theme_data[theme]["examples"]) < 3 and content:
                theme_data[theme]["examples"].append(content[:120])
            ts = ts_map.get(str(item.get("id", "")), "")
            if ts:
                theme_data[theme]["timestamps"].append(ts)
            theme_data[theme]["categories"].append(str(item.get("category", "")))

        trends: list[dict[str, Any]] = []
        for theme, data in theme_data.items():
            if data["frequency"] < _MIN_FREQUENCY:
                continue

            direction = _detect_direction(data["timestamps"])
            first_seen = min(data["timestamps"]) if data["timestamps"] else ""

            trends.append({
                "theme": theme,
                "frequency": data["frequency"],
                "direction": direction,
                "examples": data["examples"],
                "first_seen": first_seen,
            })

        trends.sort(key=lambda x: x["frequency"], reverse=True)

        return {
            "status": "success",
            "trends": trends,
        }
    except Exception as exc:
        return {
            "status": "error",
            "trends": [],
            "error": f"Trend spotting failed: {exc}",
        }


def _detect_direction(timestamps: list[str]) -> str:
    """Simple direction detection based on timestamp distribution."""
    if len(timestamps) < 2:
        return "stable"

    sorted_ts = sorted(timestamps)
    mid = len(sorted_ts) // 2
    first_half = len(sorted_ts[:mid])
    second_half = len(sorted_ts[mid:])

    if second_half > first_half * 1.5:
        return "rising"
    if first_half > second_half * 1.5:
        return "declining"
    return "stable"
