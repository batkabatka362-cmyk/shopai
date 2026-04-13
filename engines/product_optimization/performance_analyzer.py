"""Product Optimization Engine — performance analyzer.

Analyzes current product performance: conversion, revenue rank,
return rate, and identifies weaknesses.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_performance(
    products: list[dict[str, Any]],
    performance_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze performance for each product.

    Args:
        products: List of product dicts.
        performance_data: List of performance records.

    Returns:
        Structured dict with per-product performance analyses.
    """
    try:
        perf_map: dict[str, dict[str, Any]] = {}
        for p in performance_data:
            pid = str(p.get("product_id", ""))
            if pid:
                perf_map[pid] = p

        # Rank by revenue
        revenue_list = []
        for item in products:
            pid = str(item.get("id", "unknown"))
            perf = perf_map.get(pid, {})
            revenue_list.append((pid, float(perf.get("revenue", 0.0))))
        revenue_list.sort(key=lambda x: x[1], reverse=True)
        rank_map = {pid: i + 1 for i, (pid, _) in enumerate(revenue_list)}

        analyses: list[dict[str, Any]] = []

        for item in products:
            pid = str(item.get("id", "unknown"))
            perf = perf_map.get(pid, {})

            conversion_rate = float(perf.get("conversion_rate", 0.0))
            return_rate = float(perf.get("return_rate", 0.0))
            avg_rating = float(perf.get("avg_rating", 0.0))
            views = int(perf.get("views", 0))
            units_sold = int(perf.get("units_sold", 0))

            # Conversion score: 0-1 normalized (assume 10% is excellent)
            conversion_score = round(min(conversion_rate / 0.10, 1.0), 3)

            # Return score: lower is better (invert, assume 20% is worst)
            return_score = round(max(1.0 - return_rate / 0.20, 0.0), 3)

            # Overall score (weighted)
            overall_score = round(
                conversion_score * 0.40 + return_score * 0.30 +
                min(avg_rating / 5.0, 1.0) * 0.30,
                3,
            )

            weaknesses: list[str] = []
            if conversion_rate < 0.02:
                weaknesses.append("low_conversion")
            if return_rate > 0.10:
                weaknesses.append("high_returns")
            if avg_rating < 3.5:
                weaknesses.append("low_rating")
            if views > 0 and units_sold / views < 0.01:
                weaknesses.append("poor_view_to_sale")

            analyses.append({
                "product_id": pid,
                "revenue_rank": rank_map.get(pid, 0),
                "conversion_score": conversion_score,
                "return_score": return_score,
                "overall_score": overall_score,
                "weaknesses": weaknesses,
            })

        return {"status": "success", "analyses": analyses}
    except Exception as exc:
        return {"status": "error", "analyses": [], "error": f"Performance analysis failed: {exc}"}
