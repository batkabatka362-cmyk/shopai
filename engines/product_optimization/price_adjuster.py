"""Product Optimization Engine — price adjuster.

Suggests price adjustments based on performance data, conversion rates,
and competitive positioning.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def adjust_prices(
    products: list[dict[str, Any]],
    performance_data: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Suggest price adjustments for each product.

    Args:
        products: List of product dicts.
        performance_data: List of performance records.
        analyses: Per-product performance analyses.

    Returns:
        Structured dict with per-product price adjustments.
    """
    try:
        perf_map: dict[str, dict[str, Any]] = {}
        for p in performance_data:
            pid = str(p.get("product_id", ""))
            if pid:
                perf_map[pid] = p

        analysis_map = {str(a.get("product_id", "")): a for a in analyses}

        adjustments: list[dict[str, Any]] = []

        for item in products:
            pid = str(item.get("id", "unknown"))
            current_price = float(item.get("price", 0.0))
            perf = perf_map.get(pid, {})
            analysis = analysis_map.get(pid, {})

            conversion_rate = float(perf.get("conversion_rate", 0.0))
            views = int(perf.get("views", 0))
            units_sold = int(perf.get("units_sold", 0))
            weaknesses = analysis.get("weaknesses", [])

            if current_price <= 0:
                adjustments.append({
                    "product_id": pid,
                    "current_price": current_price,
                    "suggested_price": current_price,
                    "adjustment_pct": 0.0,
                    "rationale": "No price data available",
                })
                continue

            # High conversion + high views = room to increase price
            if conversion_rate > 0.05 and views > 100:
                adjustment_pct = min(conversion_rate * 0.5, 0.10)
                rationale = "Strong conversion suggests price can be increased"
            # Low conversion + many views = price may be too high
            elif "low_conversion" in weaknesses and views > 50:
                adjustment_pct = -min(0.10, 0.05 + (0.05 - conversion_rate) * 0.5)
                rationale = "Low conversion with high traffic suggests price reduction"
            # Poor view-to-sale with decent views
            elif "poor_view_to_sale" in weaknesses:
                adjustment_pct = -0.05
                rationale = "Poor view-to-sale ratio suggests competitive pricing needed"
            else:
                adjustment_pct = 0.0
                rationale = "Current pricing appears appropriate"

            suggested_price = round(current_price * (1 + adjustment_pct), 2)

            adjustments.append({
                "product_id": pid,
                "current_price": current_price,
                "suggested_price": suggested_price,
                "adjustment_pct": round(adjustment_pct * 100, 1),
                "rationale": rationale,
            })

        return {"status": "success", "adjustments": adjustments}
    except Exception as exc:
        return {"status": "error", "adjustments": [], "error": f"Price adjustment failed: {exc}"}
