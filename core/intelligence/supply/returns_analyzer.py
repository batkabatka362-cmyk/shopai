"""Returns analysis — true cost calculation and prevention strategies."""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float

logger = get_logger("intelligence.supply.returns_analyzer")

# Return reason categories and typical rates
RETURN_REASONS = {
    "not_as_described": {"typical_rate": 0.25, "preventable": True, "fix": "Improve product photos and descriptions"},
    "wrong_size": {"typical_rate": 0.20, "preventable": True, "fix": "Add detailed size chart with measurements"},
    "damaged_in_transit": {"typical_rate": 0.15, "preventable": True, "fix": "Improve packaging, add fragile labels"},
    "changed_mind": {"typical_rate": 0.20, "preventable": False, "fix": "Extend return window to reduce urgency"},
    "defective": {"typical_rate": 0.10, "preventable": True, "fix": "Quality inspection before shipping"},
    "late_delivery": {"typical_rate": 0.10, "preventable": True, "fix": "Use faster carrier, set realistic expectations"},
}


def analyze_returns(orders: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Analyze return patterns and true cost of returns.

    True return cost = return shipping + restock labor + value loss + potential churn.
    """
    if not orders:
        return {"status": "no_data"}

    total_orders = len(orders)
    returns = [o for o in orders if isinstance(o, dict) and o.get("financial_status") in ("refunded", "partially_refunded")]
    return_count = len(returns)
    return_rate = round(return_count / max(total_orders, 1) * 100, 1)

    avg_order_value = sum(safe_float(o.get("total", 0)) for o in orders if isinstance(o, dict)) / max(total_orders, 1)

    # True cost per return
    return_shipping = 8.0  # Average return shipping cost
    restock_labor = 3.0   # Labor to inspect, repackage
    value_loss = avg_order_value * 0.15  # 15% value depreciation
    customer_churn_cost = avg_order_value * 2 * 0.30  # 30% chance of losing a customer worth 2x AOV

    true_cost_per_return = round(return_shipping + restock_labor + value_loss + customer_churn_cost, 2)
    total_return_cost = round(true_cost_per_return * return_count, 2)

    return {
        "total_orders": total_orders,
        "return_count": return_count,
        "return_rate": return_rate,
        "avg_order_value": round(avg_order_value, 2),
        "true_cost_per_return": true_cost_per_return,
        "cost_breakdown": {
            "return_shipping": return_shipping,
            "restock_labor": restock_labor,
            "value_loss": round(value_loss, 2),
            "customer_churn_risk": round(customer_churn_cost, 2),
        },
        "total_return_cost": total_return_cost,
        "return_reasons": RETURN_REASONS,
        "preventable_pct": sum(v["typical_rate"] for v in RETURN_REASONS.values() if v["preventable"]) * 100,
        "recommendation": (
            f"Returns costing ${total_return_cost:,.0f}/month. "
            f"{sum(1 for v in RETURN_REASONS.values() if v['preventable'])} of {len(RETURN_REASONS)} "
            "return reasons are preventable with better photos, size charts, and packaging."
            if return_count > 0 else "No returns data available."
        ),
    }
