"""Trend Discovery Engine — synthesis engine.

Synthesize signals from search, social, and marketplace into unified trend insights.
"""
from __future__ import annotations

import copy
from typing import Any


def synthesize_signals(
    **kwargs: Any,
) -> dict[str, Any]:
    """Synthesize all signals into trend insights.

    Args:
        **kwargs: Must include all prior stage data.

    Returns:
        Structured dict with unified trends, emerging niches, hot products.
    """
    try:
        search_data = kwargs.get("search_trend_analyzer_data", {})
        social_data = kwargs.get("social_signal_tracker_data", {})
        market_data = kwargs.get("marketplace_scanner_data", {})

        search_trends = search_data.get("trends", [])
        social_signals = social_data.get("signals", [])
        hot_products = market_data.get("hot_products", [])
        emerging_niches = market_data.get("emerging_niches", [])

        # Merge search trends and social signals by topic
        trend_map: dict[str, dict[str, Any]] = {}
        for t in search_trends:
            name = t["name"].lower()
            trend_map[name] = {
                "name": t["name"],
                "source": "search",
                "strength": t["strength"],
                "direction": t["direction"],
                "sources_count": 1,
            }

        for s in social_signals:
            name = s["topic"].lower()
            if name in trend_map:
                existing = trend_map[name]
                existing["strength"] = round(min(existing["strength"] + s["strength"] * 0.5, 1.0), 2)
                existing["source"] = "multi_signal"
                existing["sources_count"] += 1
            else:
                trend_map[name] = {
                    "name": s["topic"],
                    "source": "social",
                    "strength": s["strength"],
                    "direction": s["direction"],
                    "sources_count": 1,
                }

        trends = sorted(trend_map.values(), key=lambda t: t["strength"], reverse=True)

        return {
            "status": "success",
            "result": {
                "trends": trends,
                "emerging_niches": emerging_niches,
                "hot_products": hot_products,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Signal synthesis failed: {exc}"}
