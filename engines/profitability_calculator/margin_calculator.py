"""Profitability Calculator Engine — margin calculator.

Calculates gross and net margins per product based on revenue
and cost breakdowns.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def calculate_margins(
    products: list[dict[str, Any]],
    breakdowns: list[dict[str, Any]],
    pricing: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate margins for each product.

    Args:
        products: List of product dicts.
        breakdowns: Per-product cost breakdowns.
        pricing: List of pricing record dicts.

    Returns:
        Structured dict with per-product margin results.
    """
    try:
        bd_map = {str(b.get("product_id", "")): b for b in breakdowns}
        pricing_map: dict[str, dict[str, Any]] = {}
        for p in pricing:
            pid = str(p.get("product_id", ""))
            if pid:
                pricing_map[pid] = p

        margins: list[dict[str, Any]] = []

        for item in products:
            pid = str(item.get("id", "unknown"))
            bd = bd_map.get(pid, {})
            pr = pricing_map.get(pid, {})

            effective_price = float(pr.get("effective_price", 0.0))
            if effective_price <= 0:
                selling_price = float(pr.get("selling_price", float(item.get("price", 0.0))))
                discount = float(pr.get("discount_pct", 0.0))
                effective_price = selling_price * (1 - discount / 100)

            cogs = float(bd.get("cogs", 0.0))
            total_cost = float(bd.get("total_cost_per_unit", 0.0))

            gross_margin = round(effective_price - cogs, 2)
            gross_margin_pct = round(
                (gross_margin / effective_price * 100) if effective_price > 0 else 0.0, 2,
            )

            net_margin = round(effective_price - total_cost, 2)
            net_margin_pct = round(
                (net_margin / effective_price * 100) if effective_price > 0 else 0.0, 2,
            )

            margins.append({
                "product_id": pid,
                "revenue_per_unit": round(effective_price, 2),
                "cost_per_unit": total_cost,
                "gross_margin": gross_margin,
                "gross_margin_pct": gross_margin_pct,
                "net_margin": net_margin,
                "net_margin_pct": net_margin_pct,
            })

        return {"status": "success", "margins": margins}
    except Exception as exc:
        return {"status": "error", "margins": [], "error": f"Margin calculation failed: {exc}"}
