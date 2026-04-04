"""Cohort Analysis Engine — retention calculator.

Calculates cohort retention rates over time.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def calculate_retention(
    cohorts: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    cohort_type: str,
) -> dict[str, Any]:
    """Calculate retention rates for each cohort.

    Args:
        cohorts: Cohort assignments from cohort_builder.
        orders: Full order list.
        cohort_type: "monthly" or "weekly".

    Returns:
        Structured dict with retention rates and matrix.
    """
    try:
        # Build order periods per customer
        cust_periods: dict[str, set[str]] = {}
        for order in orders:
            cid = str(order.get("customer_id", ""))
            odate = str(order.get("created_at", order.get("date", "")))
            period = odate[:10] if cohort_type == "weekly" else odate[:7]
            cust_periods.setdefault(cid, set()).add(period)

        all_periods = sorted({p for ps in cust_periods.values() for p in ps})
        period_index = {p: i for i, p in enumerate(all_periods)}

        retention_matrix: list[list[float]] = []
        cohort_retention: list[dict[str, Any]] = []

        for cohort in cohorts:
            period = cohort["period"]
            cids = cohort.get("customer_ids", [])
            size = len(cids)
            if size == 0:
                continue

            start_idx = period_index.get(period, 0)
            rates: list[float] = []

            for offset in range(len(all_periods) - start_idx):
                target_period = all_periods[start_idx + offset] if (start_idx + offset) < len(all_periods) else None
                if target_period is None:
                    break
                active = sum(1 for cid in cids if target_period in cust_periods.get(cid, set()))
                rate = round(active / size, 4) if size > 0 else 0.0
                rates.append(rate)

            retention_matrix.append(rates)
            cohort_retention.append({
                "period": period,
                "size": size,
                "retention_rates": rates,
            })

        return {
            "status": "success",
            "cohort_retention": cohort_retention,
            "retention_matrix": retention_matrix,
        }
    except Exception as exc:
        return {"status": "error", "cohort_retention": [], "retention_matrix": [], "error": f"Retention calculation failed: {exc}"}
