"""Profit Optimization Engine — data aggregator.

Aggregates sales, ads, costs, and performance data into a unified
metrics structure for downstream processing.

No business logic — just normalization, defaults, and merging.
"""
from __future__ import annotations

import copy
from typing import Any


def aggregate_data(
    sales: dict[str, Any],
    ads: dict[str, Any],
    costs: dict[str, Any],
    performance: dict[str, Any],
) -> dict[str, Any]:
    """Aggregate raw input data into a unified structure.

    Applies defaults for missing fields, normalizes types, and
    produces a single dict that all downstream modules can rely on.

    Args:
        sales: SalesData dict.
        ads: AdsData dict.
        costs: CostData dict.
        performance: PerformanceData dict.

    Returns:
        Structured dict with normalized, merged data.
    """
    try:
        s = copy.deepcopy(sales) if isinstance(sales, dict) else {}
        a = copy.deepcopy(ads) if isinstance(ads, dict) else {}
        c = copy.deepcopy(costs) if isinstance(costs, dict) else {}
        p = copy.deepcopy(performance) if isinstance(performance, dict) else {}

        aggregated = {
            "sales": _normalize_sales(s),
            "ads": _normalize_ads(a),
            "costs": _normalize_costs(c),
            "performance": _normalize_performance(p),
        }

        # Derived convenience fields
        total_revenue = aggregated["sales"]["total_revenue"]
        total_ad_spend = aggregated["ads"]["total_spend"]
        total_costs = _sum_costs(aggregated["costs"])

        aggregated["summary"] = {
            "total_revenue": total_revenue,
            "total_ad_spend": total_ad_spend,
            "total_fixed_costs": total_costs,
            "total_units": aggregated["sales"]["units_sold"],
            "total_orders": aggregated["sales"]["orders"],
        }

        return {
            "status": "success",
            "aggregated": aggregated,
        }
    except Exception as exc:
        return {
            "status": "error",
            "aggregated": {},
            "error": f"Data aggregation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _normalize_sales(s: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults and enforce types for sales data."""
    total_revenue = float(s.get("total_revenue", 0.0))
    units_sold = int(s.get("units_sold", 0))
    orders = int(s.get("orders", 0))
    refunds = int(s.get("refunds", 0))

    if orders > 0:
        aov = total_revenue / orders
    else:
        aov = float(s.get("avg_order_value", 0.0))

    return {
        "total_revenue": total_revenue,
        "units_sold": units_sold,
        "orders": orders,
        "avg_order_value": round(aov, 2),
        "refunds": refunds,
    }


def _normalize_ads(a: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults and enforce types for ads data."""
    return {
        "total_spend": float(a.get("total_spend", 0.0)),
        "impressions": int(a.get("impressions", 0)),
        "clicks": int(a.get("clicks", 0)),
        "conversions": int(a.get("conversions", 0)),
        "platform_breakdown": dict(a.get("platform_breakdown", {})),
    }


def _normalize_costs(c: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults and enforce types for cost data."""
    return {
        "cogs": float(c.get("cogs", 0.0)),
        "shipping": float(c.get("shipping", 0.0)),
        "platform_fees": float(c.get("platform_fees", 0.0)),
        "tools": float(c.get("tools", 0.0)),
        "labor": float(c.get("labor", 0.0)),
    }


def _normalize_performance(p: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults and enforce types for performance data."""
    return {
        "conversion_rate": float(p.get("conversion_rate", 0.0)),
        "cart_abandonment": float(p.get("cart_abandonment", 0.0)),
        "return_rate": float(p.get("return_rate", 0.0)),
        "customer_satisfaction": float(p.get("customer_satisfaction", 0.0)),
    }


def _sum_costs(costs: dict[str, Any]) -> float:
    """Sum all cost line items."""
    return (
        costs.get("cogs", 0.0)
        + costs.get("shipping", 0.0)
        + costs.get("platform_fees", 0.0)
        + costs.get("tools", 0.0)
        + costs.get("labor", 0.0)
    )
