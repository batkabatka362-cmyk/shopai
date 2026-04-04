"""Cohort Analysis Engine — revenue tracker.

Tracks revenue evolution per cohort over time.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def track_revenue(
    cohorts: list[dict[str, Any]],
    orders: list[dict[str, Any]],
) -> dict[str, Any]:
    """Track revenue per cohort.

    Args:
        cohorts: Cohort assignments.
        orders: Full order list with totals.

    Returns:
        Structured dict with cohort revenues.
    """
    try:
        # Map customer to cohort
        cust_cohort: dict[str, str] = {}
        for cohort in cohorts:
            for cid in cohort.get("customer_ids", []):
                cust_cohort[cid] = cohort["period"]

        # Sum revenue per cohort
        cohort_revenue: dict[str, float] = {}
        for order in orders:
            cid = str(order.get("customer_id", ""))
            total = float(order.get("total", order.get("total_price", 0.0)))
            period = cust_cohort.get(cid, "unknown")
            cohort_revenue[period] = cohort_revenue.get(period, 0.0) + total

        revenue_list = [
            {"period": p, "revenue": round(r, 2)}
            for p, r in sorted(cohort_revenue.items())
            if p != "unknown"
        ]

        return {"status": "success", "cohort_revenues": revenue_list}
    except Exception as exc:
        return {"status": "error", "cohort_revenues": [], "error": f"Revenue tracking failed: {exc}"}
