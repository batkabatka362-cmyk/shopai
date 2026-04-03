"""Trend Discovery Engine — search trend analyzer.

Analyze search trend data to identify rising/falling interest patterns.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_search_trends(
    **kwargs: Any,
) -> dict[str, Any]:
    """Analyze search trend data.

    Args:
        **kwargs: Must include 'category' and 'search_data'.

    Returns:
        Structured dict with search trend analysis.
    """
    try:
        category = str(kwargs.get("category", ""))
        search_data = copy.deepcopy(kwargs.get("search_data", {}))
        keywords = search_data.get("keywords", [])

        trends: list[dict[str, Any]] = []

        for kw in keywords:
            name = str(kw.get("keyword", ""))
            current_vol = int(kw.get("current_volume", 0))
            prev_vol = int(kw.get("previous_volume", 0))

            if prev_vol > 0:
                growth = round((current_vol - prev_vol) / prev_vol * 100, 1)
            else:
                growth = 100.0 if current_vol > 0 else 0.0

            if growth > 50:
                direction = "surging"
                strength = min(1.0, growth / 200)
            elif growth > 10:
                direction = "rising"
                strength = min(0.7, growth / 100)
            elif growth > -10:
                direction = "stable"
                strength = 0.3
            else:
                direction = "declining"
                strength = 0.1

            trends.append({
                "name": name,
                "source": "search",
                "volume": current_vol,
                "growth_pct": growth,
                "direction": direction,
                "strength": round(strength, 2),
            })

        trends.sort(key=lambda t: t["strength"], reverse=True)

        return {
            "status": "success",
            "result": {"trends": trends, "category": category},
        }
    except Exception as exc:
        return {"status": "error", "error": f"Search trend analysis failed: {exc}"}
