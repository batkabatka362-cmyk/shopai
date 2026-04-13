"""Market Research Engine — trend synthesizer.

Synthesize market trends from multiple data sources.
"""
from __future__ import annotations

import copy
from typing import Any


def synthesize_trends(
    **kwargs: Any,
) -> dict[str, Any]:
    """Synthesize market trends.

    Args:
        **kwargs: Must include 'trends' list and search_data.

    Returns:
        Structured dict with synthesized trend insights.
    """
    try:
        trends = copy.deepcopy(kwargs.get("trends", []))
        search_data = kwargs.get("search_data", {})
        search_trends = search_data.get("search_trends", [])

        synthesized: list[dict[str, Any]] = []

        for trend in trends:
            name = str(trend.get("name", ""))
            strength = float(trend.get("strength", 0.5))
            direction = str(trend.get("direction", "stable"))

            # Corroborate with search data
            corroborated = any(
                name.lower() in str(st.get("keyword", "")).lower()
                for st in search_trends
            )
            if corroborated:
                strength = min(strength * 1.3, 1.0)

            synthesized.append({
                "name": name,
                "strength": round(strength, 2),
                "direction": direction,
                "corroborated": corroborated,
                "source": trend.get("source", "market_data"),
            })

        # Sort by strength
        synthesized.sort(key=lambda t: t["strength"], reverse=True)

        return {
            "status": "success",
            "result": {"trends": synthesized},
        }
    except Exception as exc:
        return {"status": "error", "error": f"Trend synthesis failed: {exc}"}
