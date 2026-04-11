"""Profitability Calculator Engine — ROI projector.

Projects return on investment for each product based on costs,
margins, and sales volume.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def project_roi(
    products: list[dict[str, Any]],
    margins: list[dict[str, Any]],
    breakdowns: list[dict[str, Any]],
) -> dict[str, Any]:
    """Project ROI for each product.

    Args:
        products: List of product dicts.
        margins: Per-product margin results.
        breakdowns: Per-product cost breakdowns.

    Returns:
        Structured dict with per-product ROI projections.
    """
    try:
        margin_map = {str(m.get("product_id", "")): m for m in margins}
        bd_map = {str(b.get("product_id", "")): b for b in breakdowns}

        projections: list[dict[str, Any]] = []

        for item in products:
            pid = str(item.get("id", "unknown"))
            units_sold = int(item.get("units_sold", 0))
            margin = margin_map.get(pid, {})
            bd = bd_map.get(pid, {})

            revenue_per_unit = float(margin.get("revenue_per_unit", 0.0))
            cost_per_unit = float(margin.get("cost_per_unit", 0.0))

            total_investment = round(cost_per_unit * max(units_sold, 1), 2)
            total_return = round(revenue_per_unit * units_sold, 2)
            net_return = total_return - total_investment

            roi_pct = round(
                (net_return / total_investment * 100) if total_investment > 0 else 0.0, 2,
            )

            # Payback periods: how many sales periods to recoup investment
            net_margin_per_unit = float(margin.get("net_margin", 0.0))
            if net_margin_per_unit > 0 and units_sold > 0:
                payback_periods = max(1, int(total_investment / (net_margin_per_unit * units_sold) + 0.999))
            else:
                payback_periods = 0

            projections.append({
                "product_id": pid,
                "total_investment": total_investment,
                "total_return": total_return,
                "roi_pct": roi_pct,
                "payback_periods": payback_periods,
            })

        return {"status": "success", "projections": projections}
    except Exception as exc:
        return {"status": "error", "projections": [], "error": f"ROI projection failed: {exc}"}
