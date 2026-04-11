"""LTV:CAC Dashboard Engine — LTV calculator.

Calculates customer lifetime value from order history.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def calculate_ltv(
    customers: list[dict[str, Any]],
    orders: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate customer lifetime value.

    Args:
        customers: Customer list with segments.
        orders: Order list with totals.

    Returns:
        Structured dict with LTV by segment and overall.
    """
    try:
        # Revenue per customer
        cust_revenue: dict[str, float] = {}
        for order in orders:
            cid = str(order.get("customer_id", ""))
            total = float(order.get("total", order.get("total_price", 0.0)))
            cust_revenue[cid] = cust_revenue.get(cid, 0.0) + total

        # Customer segments
        cust_seg: dict[str, str] = {}
        for c in customers:
            cid = str(c.get("id", c.get("customer_id", "")))
            seg = str(c.get("segment", "default"))
            cust_seg[cid] = seg

        # Overall average LTV
        all_ltvs = list(cust_revenue.values())
        avg_ltv = round(sum(all_ltvs) / len(all_ltvs), 2) if all_ltvs else 0.0

        # LTV by segment
        seg_totals: dict[str, list[float]] = {}
        for cid, rev in cust_revenue.items():
            seg = cust_seg.get(cid, "default")
            seg_totals.setdefault(seg, []).append(rev)

        by_segment: dict[str, float] = {}
        for seg, values in seg_totals.items():
            by_segment[seg] = round(sum(values) / len(values), 2) if values else 0.0

        return {
            "status": "success",
            "ltv": {"average": avg_ltv, "by_segment": by_segment},
        }
    except Exception as exc:
        return {"status": "error", "ltv": {}, "error": f"LTV calculation failed: {exc}"}
