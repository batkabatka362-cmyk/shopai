"""Working capital analysis — Cash Conversion Cycle.

CCC = DIO + DSO - DPO
  DIO = Days Inventory Outstanding
  DSO = Days Sales Outstanding (Shopify = 2-3 days)
  DPO = Days Payable Outstanding (supplier terms)
"""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_float


def analyze_working_capital(orders: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze working capital and cash conversion cycle."""
    if not orders:
        return {"status": "no_data"}

    order_values = [safe_float(o.get("total", 0)) for o in orders if isinstance(o, dict)]
    total_revenue = sum(order_values)
    daily_revenue = total_revenue / 30

    dso = 3   # Shopify pays out in 2-3 business days
    dpo = 30  # Net 30 supplier terms assumed

    avg_inventory_value = total_revenue * 0.4
    dio = round(avg_inventory_value / max(daily_revenue * 0.4, 0.01), 1) if daily_revenue > 0 else 0

    ccc = round(dio + dso - dpo, 1)

    cash_needed_per_day = daily_revenue * 0.6
    monthly_cash_need = round(cash_needed_per_day * 30, 2)

    return {
        "daily_revenue": round(daily_revenue, 2),
        "cash_conversion_cycle_days": ccc,
        "days_inventory_outstanding": dio,
        "days_sales_outstanding": dso,
        "days_payable_outstanding": dpo,
        "monthly_cash_requirement": monthly_cash_need,
        "interpretation": (
            "Negative CCC = good (you collect before paying suppliers)"
            if ccc < 0 else
            f"Positive CCC ({ccc} days) = you need working capital to bridge the gap"
        ),
        "recommendations": _working_capital_recommendations(ccc, dio, daily_revenue),
    }


def _working_capital_recommendations(ccc: float, dio: float, daily_revenue: float) -> list[str]:
    recs = []
    if ccc > 15:
        recs.append("Negotiate longer payment terms with suppliers (Net 45/60)")
    if dio > 45:
        recs.append("Inventory sitting too long — run clearance on slow movers")
    if daily_revenue > 500 and ccc > 0:
        recs.append(f"Consider a line of credit for ${round(ccc * daily_revenue * 0.6, 0)} working capital gap")
    if not recs:
        recs.append("Working capital position is healthy")
    return recs
