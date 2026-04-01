"""Chargeback risk assessment.

>1% chargeback rate = Shopify Payments account termination risk.
Estimates rate from refund data when direct chargeback data unavailable.
"""
from __future__ import annotations

from typing import Any


def assess_chargeback_risk(orders: list[dict[str, Any]]) -> dict[str, Any]:
    """Assess chargeback risk level."""
    if not orders:
        return {"status": "no_data"}

    total_orders = len(orders)
    chargebacks = sum(
        1 for o in orders
        if isinstance(o, dict) and o.get("financial_status") == "refunded"
        and o.get("cancel_reason") == "fraud"
    )
    refunds = sum(
        1 for o in orders
        if isinstance(o, dict) and o.get("financial_status") in ("refunded", "partially_refunded")
    )

    chargeback_rate = chargebacks / max(total_orders, 1)
    refund_rate = refunds / max(total_orders, 1)
    estimated_chargeback_rate = max(chargeback_rate, refund_rate * 0.1)

    risk_level = "low"
    if estimated_chargeback_rate > 0.01:
        risk_level = "critical"
    elif estimated_chargeback_rate > 0.005:
        risk_level = "high"
    elif estimated_chargeback_rate > 0.002:
        risk_level = "medium"

    return {
        "total_orders": total_orders,
        "known_chargebacks": chargebacks,
        "refunds": refunds,
        "refund_rate": round(refund_rate * 100, 2),
        "estimated_chargeback_rate": round(estimated_chargeback_rate * 100, 3),
        "risk_level": risk_level,
        "threshold": "1% = Shopify Payments account termination",
        "recommendations": _chargeback_recommendations(risk_level),
    }


def _chargeback_recommendations(risk_level: str) -> list[str]:
    recs = []
    if risk_level == "critical":
        recs.append("URGENT: Chargeback rate exceeds 1% — Shopify Payments at risk of termination")
        recs.append("Enable fraud analysis on all orders")
        recs.append("Require signature confirmation on orders > $250")
    if risk_level in ("critical", "high"):
        recs.append("Add clear product descriptions and photos to reduce 'not as described' disputes")
        recs.append("Send shipping confirmation with tracking immediately")
        recs.append("Make return policy prominent and easy to find")
    if risk_level == "medium":
        recs.append("Monitor chargeback rate weekly")
        recs.append("Consider adding chargeback prevention tools (Verifi, Ethoca)")
    if not recs:
        recs.append("Chargeback risk is low — maintain current practices")
    return recs
