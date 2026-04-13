"""Supplier Engine — performance scorer.

Score supplier performance across quality, delivery, and cost dimensions.
"""
from __future__ import annotations

import copy
from typing import Any


def score_performance(
    **kwargs: Any,
) -> dict[str, Any]:
    """Score supplier performance.

    Args:
        **kwargs: Must include 'suppliers' list, 'orders' list, 'quality_data' list.

    Returns:
        Structured dict with per-supplier performance scores.
    """
    try:
        suppliers = copy.deepcopy(kwargs.get("suppliers", []))
        orders = kwargs.get("orders", [])
        quality_data = kwargs.get("quality_data", [])

        # Build lookup maps
        orders_by_supplier: dict[str, list] = {}
        for o in orders:
            sid = str(o.get("supplier_id", ""))
            orders_by_supplier.setdefault(sid, []).append(o)

        quality_by_supplier: dict[str, list] = {}
        for q in quality_data:
            sid = str(q.get("supplier_id", ""))
            quality_by_supplier.setdefault(sid, []).append(q)

        scores: list[dict[str, Any]] = []

        for sup in suppliers:
            sid = str(sup.get("id", "unknown"))
            sup_orders = orders_by_supplier.get(sid, [])
            sup_quality = quality_by_supplier.get(sid, [])

            # Delivery score: on-time percentage
            total_orders = len(sup_orders)
            on_time = sum(1 for o in sup_orders if o.get("on_time", True))
            delivery_score = round(on_time / max(total_orders, 1), 2)

            # Quality score: average quality rating
            q_ratings = [float(q.get("rating", 3.0)) for q in sup_quality]
            quality_score = round(sum(q_ratings) / max(len(q_ratings), 1) / 5.0, 2)

            # Cost score: based on cost competitiveness (lower = better)
            costs = [float(o.get("unit_cost", 0)) for o in sup_orders if o.get("unit_cost")]
            avg_cost = sum(costs) / max(len(costs), 1) if costs else 0
            cost_score = round(max(0, 1.0 - avg_cost / 100.0), 2)

            overall = round((delivery_score * 0.35 + quality_score * 0.40 + cost_score * 0.25), 2)

            scores.append({
                "supplier_id": sid,
                "name": sup.get("name", ""),
                "delivery_score": delivery_score,
                "quality_score": quality_score,
                "cost_score": cost_score,
                "overall": overall,
                "total_orders": total_orders,
            })

        return {
            "status": "success",
            "result": {"scores": scores, "total_suppliers": len(scores)},
        }
    except Exception as exc:
        return {"status": "error", "error": f"Performance scoring failed: {exc}"}
