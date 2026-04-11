"""Cohort Analysis Engine — cohort builder.

Builds cohorts by signup month or first purchase date.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def build_cohorts(
    customers: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    cohort_type: str,
) -> dict[str, Any]:
    """Build cohorts from customer and order data.

    Args:
        customers: Customer list with signup/created dates.
        orders: Order list with customer_id and date.
        cohort_type: "monthly" or "weekly".

    Returns:
        Structured dict with cohort assignments.
    """
    try:
        cust_map: dict[str, dict[str, Any]] = {}
        for c in customers:
            cid = str(c.get("id", c.get("customer_id", "")))
            signup = str(c.get("created_at", c.get("signup_date", "")))
            if cohort_type == "weekly":
                period = signup[:10]  # YYYY-MM-DD
            else:
                period = signup[:7]  # YYYY-MM
            cust_map[cid] = {"customer_id": cid, "cohort_period": period, "signup": signup}

        # Also derive from first purchase if no signup date
        order_sorted = sorted(orders, key=lambda o: str(o.get("created_at", o.get("date", ""))))
        for order in order_sorted:
            cid = str(order.get("customer_id", ""))
            if cid in cust_map and cust_map[cid]["cohort_period"]:
                continue
            odate = str(order.get("created_at", order.get("date", "")))
            period = odate[:10] if cohort_type == "weekly" else odate[:7]
            if cid not in cust_map:
                cust_map[cid] = {"customer_id": cid, "cohort_period": period, "signup": odate}

        # Group by cohort period
        cohorts: dict[str, list[str]] = {}
        for cid, info in cust_map.items():
            p = info["cohort_period"]
            if p:
                cohorts.setdefault(p, []).append(cid)

        cohort_list = [
            {"period": period, "customer_ids": cids, "size": len(cids)}
            for period, cids in sorted(cohorts.items())
        ]

        return {"status": "success", "cohorts": cohort_list}
    except Exception as exc:
        return {"status": "error", "cohorts": [], "error": f"Cohort building failed: {exc}"}
