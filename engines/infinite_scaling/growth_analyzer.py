"""Infinite Scaling Engine — growth analyzer.

Analyze current growth trajectory from business metrics.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_growth(
    **kwargs: Any,
) -> dict[str, Any]:
    """Analyze growth trajectory.

    Args:
        **kwargs: Must include 'metrics' dict.

    Returns:
        Structured dict with growth analysis.
    """
    try:
        metrics = copy.deepcopy(kwargs.get("metrics", {}))

        revenue = float(metrics.get("monthly_revenue", 0))
        prev_revenue = float(metrics.get("prev_month_revenue", 0))
        customers = int(metrics.get("active_customers", 0))
        prev_customers = int(metrics.get("prev_month_customers", 0))
        orders = int(metrics.get("monthly_orders", 0))

        # Revenue growth
        rev_growth = round((revenue - prev_revenue) / max(prev_revenue, 1) * 100, 1) if prev_revenue else 0.0
        # Customer growth
        cust_growth = round((customers - prev_customers) / max(prev_customers, 1) * 100, 1) if prev_customers else 0.0
        # Average order value
        aov = round(revenue / max(orders, 1), 2)

        # Growth phase classification
        if rev_growth > 20:
            phase = "hypergrowth"
        elif rev_growth > 5:
            phase = "growth"
        elif rev_growth > 0:
            phase = "stable"
        else:
            phase = "declining"

        return {
            "status": "success",
            "result": {
                "growth_trajectory": {
                    "revenue_growth_pct": rev_growth,
                    "customer_growth_pct": cust_growth,
                    "aov": aov,
                    "phase": phase,
                    "monthly_revenue": revenue,
                    "active_customers": customers,
                    "monthly_orders": orders,
                },
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Growth analysis failed: {exc}"}
