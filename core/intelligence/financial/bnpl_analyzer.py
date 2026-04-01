"""BNPL (Buy Now Pay Later) analyzer — provider ROI comparison.

Compares Afterpay, Klarna, Affirm, Shop Pay Installments.
Each has different merchant fees, AOV lift, and conversion lift.
Calculates net monthly benefit per provider.
"""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_float


BNPL_PROVIDERS = {
    "afterpay": {"merchant_fee_pct": 0.06, "merchant_fee_fixed": 0.30, "avg_aov_lift": 0.40, "avg_cvr_lift": 0.20},
    "klarna": {"merchant_fee_pct": 0.0399, "merchant_fee_fixed": 0.30, "avg_aov_lift": 0.45, "avg_cvr_lift": 0.25},
    "affirm": {"merchant_fee_pct": 0.055, "merchant_fee_fixed": 0.30, "avg_aov_lift": 0.50, "avg_cvr_lift": 0.20},
    "shop_pay_installments": {"merchant_fee_pct": 0.052, "merchant_fee_fixed": 0.0, "avg_aov_lift": 0.35, "avg_cvr_lift": 0.15},
}


def analyze_bnpl(
    products: list[dict[str, Any]],
    orders: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze Buy Now Pay Later opportunity."""
    prices = [safe_float(p.get("price", 0)) for p in products if isinstance(p, dict)]
    if not prices:
        return {"status": "no_data"}

    avg_price = sum(prices) / len(prices)
    order_values = [safe_float(o.get("total", 0)) for o in orders if isinstance(o, dict)]
    current_aov = sum(order_values) / max(len(order_values), 1) if order_values else avg_price
    monthly_revenue = sum(order_values)
    monthly_orders = len(order_values)

    bnpl_suitable = 50 <= avg_price <= 3000

    results = []
    for provider, config in BNPL_PROVIDERS.items():
        projected_aov = current_aov * (1 + config["avg_aov_lift"])
        projected_orders = monthly_orders * (1 + config["avg_cvr_lift"])
        projected_revenue = projected_aov * projected_orders

        bnpl_adoption = 0.20
        bnpl_revenue = projected_revenue * bnpl_adoption
        bnpl_fees = bnpl_revenue * config["merchant_fee_pct"] + projected_orders * bnpl_adoption * config["merchant_fee_fixed"]

        incremental_revenue = projected_revenue - monthly_revenue
        net_benefit = incremental_revenue - bnpl_fees

        results.append({
            "provider": provider,
            "merchant_fee": f"{config['merchant_fee_pct']*100:.1f}%",
            "projected_aov_lift": f"+{config['avg_aov_lift']*100:.0f}%",
            "projected_cvr_lift": f"+{config['avg_cvr_lift']*100:.0f}%",
            "projected_monthly_revenue": round(projected_revenue, 2),
            "estimated_monthly_fees": round(bnpl_fees, 2),
            "net_monthly_benefit": round(net_benefit, 2),
            "roi": round(net_benefit / max(bnpl_fees, 1) * 100, 1),
        })

    results.sort(key=lambda r: r["net_monthly_benefit"], reverse=True)

    return {
        "suitable_for_bnpl": bnpl_suitable,
        "current_aov": round(current_aov, 2),
        "avg_product_price": round(avg_price, 2),
        "providers": results,
        "recommendation": results[0]["provider"] if results and results[0]["net_monthly_benefit"] > 0 else "none",
    }
