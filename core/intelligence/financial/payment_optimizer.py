"""Payment processor comparison and optimization.

Compares Shopify Payments, Stripe, PayPal, Square on fees,
chargeback costs, and hold periods.
"""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_float


PAYMENT_PROCESSORS = {
    "shopify_payments": {"pct": 0.029, "fixed": 0.30, "chargeback_fee": 15, "hold_days": 2},
    "stripe": {"pct": 0.029, "fixed": 0.30, "chargeback_fee": 15, "hold_days": 2},
    "paypal": {"pct": 0.0349, "fixed": 0.49, "chargeback_fee": 20, "hold_days": 1},
    "square": {"pct": 0.029, "fixed": 0.30, "chargeback_fee": 0, "hold_days": 1},
}


def optimize_payment_processor(
    orders: list[dict[str, Any]],
    current_processor: str = "shopify_payments",
) -> dict[str, Any]:
    """Compare payment processors and find the cheapest option."""
    order_values = [safe_float(o.get("total", 0)) for o in orders if isinstance(o, dict)]
    if not order_values:
        return {"status": "no_data"}

    total_revenue = sum(order_values)
    order_count = len(order_values)
    avg_order = total_revenue / max(order_count, 1)

    comparisons = []
    for processor, config in PAYMENT_PROCESSORS.items():
        fees = total_revenue * config["pct"] + order_count * config["fixed"]
        fee_pct = fees / max(total_revenue, 1) * 100
        comparisons.append({
            "processor": processor,
            "monthly_fees": round(fees, 2),
            "effective_rate": round(fee_pct, 2),
            "per_transaction": round(avg_order * config["pct"] + config["fixed"], 2),
            "chargeback_fee": config["chargeback_fee"],
            "hold_days": config["hold_days"],
            "is_current": processor == current_processor,
        })

    comparisons.sort(key=lambda c: c["monthly_fees"])
    cheapest = comparisons[0]
    current = next((c for c in comparisons if c["is_current"]), comparisons[0])
    savings = round(current["monthly_fees"] - cheapest["monthly_fees"], 2)

    return {
        "comparisons": comparisons,
        "cheapest": cheapest["processor"],
        "current": current_processor,
        "potential_monthly_savings": savings,
        "recommendation": (
            f"Switch to {cheapest['processor']} to save ${savings}/month"
            if savings > 10 else "Current processor is optimal or near-optimal"
        ),
    }
