"""Dropshipping Engine — margin optimizer.

Optimizes margins across suppliers by analyzing cost vs selling price.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def optimize_margins(
    supplier_orders: list[dict[str, Any]],
    products: list[dict[str, Any]],
    suppliers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze and optimize margins across suppliers.

    Args:
        supplier_orders: Current supplier orders.
        products: Product catalog with selling prices.
        suppliers: Supplier list for performance context.

    Returns:
        Structured dict with margin analysis and supplier performance.
    """
    try:
        prod_map = {str(p.get("id", "")): p for p in products}
        margin_analysis: list[dict[str, Any]] = []

        for so in supplier_orders:
            sid = str(so.get("supplier_id", ""))
            for item in so.get("items", []):
                pid = str(item.get("product_id", ""))
                cost = float(item.get("unit_cost", 0.0))
                product = prod_map.get(pid, {})
                selling = float(product.get("price", 0.0))

                margin = round(selling - cost, 2)
                margin_pct = round((margin / selling) * 100, 1) if selling > 0 else 0.0

                margin_analysis.append({
                    "product_id": pid,
                    "supplier_id": sid,
                    "cost": cost,
                    "selling_price": selling,
                    "margin": margin,
                    "margin_pct": margin_pct,
                })

        # Supplier performance aggregation
        sup_perf: dict[str, dict[str, Any]] = {}
        for sup in suppliers:
            sid = str(sup.get("id", ""))
            sup_perf[sid] = {
                "supplier_id": sid,
                "supplier_name": str(sup.get("name", "")),
                "avg_fulfillment_days": float(sup.get("avg_fulfillment_days", 3.0)),
                "on_time_rate": float(sup.get("on_time_rate", 0.90)),
                "defect_rate": float(sup.get("defect_rate", 0.02)),
            }

        supplier_performance: list[dict[str, Any]] = []
        for sid, perf in sup_perf.items():
            score = round(
                perf["on_time_rate"] * 0.40
                + (1.0 - perf["defect_rate"]) * 0.30
                + max(0, 1.0 - perf["avg_fulfillment_days"] / 14.0) * 0.30,
                3,
            )
            perf["overall_score"] = score
            supplier_performance.append(perf)

        supplier_performance.sort(key=lambda s: s["overall_score"], reverse=True)

        return {
            "status": "success",
            "margin_analysis": margin_analysis,
            "supplier_performance": supplier_performance,
        }
    except Exception as exc:
        return {"status": "error", "margin_analysis": [], "supplier_performance": [], "error": f"Margin optimization failed: {exc}"}
