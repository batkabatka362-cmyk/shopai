"""Contribution margin per SKU — the REAL profitability metric.

Contribution Margin = Revenue - COGS - Variable Costs
Variable Costs = payment fees + shipping + packaging + returns

Unlike gross margin, this shows TRUE profit after all touch costs.
"""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_float, safe_int


def contribution_margin_by_sku(
    products: list[dict[str, Any]],
    orders: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate true contribution margin per SKU."""
    sku_data: dict[str, dict[str, Any]] = {}

    product_lookup: dict[str, dict[str, Any]] = {}
    for p in products:
        if isinstance(p, dict):
            pid = str(p.get("id", ""))
            if pid:
                product_lookup[pid] = p

    for order in orders:
        if not isinstance(order, dict):
            continue
        for item in order.get("line_items", []):
            if not isinstance(item, dict):
                continue
            pid = str(item.get("product_id", ""))
            qty = safe_int(item.get("quantity", 1))
            revenue = safe_float(item.get("price", 0)) * qty

            product = product_lookup.get(pid, {})
            cost = safe_float(item.get("cost", 0)) or safe_float(product.get("cost", 0))
            cogs = cost * qty

            if pid not in sku_data:
                sku_data[pid] = {
                    "product_id": pid,
                    "name": product.get("title", product.get("name", f"Product {pid}")),
                    "units_sold": 0,
                    "revenue": 0,
                    "cogs": 0,
                }

            sku_data[pid]["units_sold"] += qty
            sku_data[pid]["revenue"] += revenue
            sku_data[pid]["cogs"] += cogs

    results = []
    for pid, data in sku_data.items():
        revenue = data["revenue"]
        cogs = data["cogs"]
        units = data["units_sold"]

        payment_fee = revenue * 0.029 + units * 0.30
        shipping_est = units * 7.0
        packaging = units * 1.50
        return_cost = units * 0.08 * 6.0  # 8% return rate * $6 return shipping

        total_variable = cogs + payment_fee + shipping_est + packaging + return_cost
        contribution = revenue - total_variable
        margin_pct = round(contribution / max(revenue, 0.01) * 100, 1)

        results.append({
            "product_id": pid,
            "name": data["name"],
            "units_sold": units,
            "revenue": round(revenue, 2),
            "cogs": round(cogs, 2),
            "variable_costs": {
                "payment_fees": round(payment_fee, 2),
                "shipping": round(shipping_est, 2),
                "packaging": round(packaging, 2),
                "returns": round(return_cost, 2),
            },
            "contribution_margin": round(contribution, 2),
            "contribution_margin_pct": margin_pct,
            "status": "profitable" if margin_pct > 0 else "unprofitable",
        })

    results.sort(key=lambda r: r["contribution_margin"], reverse=True)

    profitable = [r for r in results if r["contribution_margin_pct"] > 0]
    unprofitable = [r for r in results if r["contribution_margin_pct"] <= 0]

    return {
        "skus_analyzed": len(results),
        "profitable_skus": len(profitable),
        "unprofitable_skus": len(unprofitable),
        "details": results,
        "recommendation": (
            f"{len(unprofitable)} SKUs are unprofitable after variable costs. "
            "Consider price increases or discontinuation."
            if unprofitable else "All SKUs are profitable."
        ),
    }
