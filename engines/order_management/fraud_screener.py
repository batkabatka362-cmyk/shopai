"""Order Management Engine — fraud screener.

Quick pre-screen risk assessment for incoming orders.
NOT the full fraud_detection engine — just a fast heuristic check.

All scoring is deterministic based on order attributes.
"""
from __future__ import annotations

import copy
from typing import Any

_FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "aol.com", "mail.com", "protonmail.com", "yandex.com",
    "gmx.com", "zoho.com",
}


def screen_for_fraud(order: dict[str, Any]) -> dict[str, Any]:
    """Run a quick fraud pre-screen on an order.

    Args:
        order: The full order dict.

    Returns:
        Structured dict with risk assessment.
    """
    try:
        order = copy.deepcopy(order)
        flags: list[str] = []
        risk_score = 0.0

        total_price = float(order.get("total_price", 0))
        email = str(order.get("email", ""))
        customer = order.get("customer", {})
        orders_count = int(customer.get("orders_count", 0))
        shipping_addr = order.get("shipping_address", {})
        billing_addr = order.get("billing_address", {})

        # ---- Flag: new customer ----
        is_new_customer = orders_count == 0

        # ---- Flag: free email domain ----
        email_domain = email.split("@")[-1].lower() if "@" in email else ""
        is_free_email = email_domain in _FREE_EMAIL_DOMAINS

        # ---- Rule: high value + new customer = medium risk ----
        if total_price > 500 and is_new_customer:
            risk_score += 0.3
            flags.append("high_value_new_customer")

        # ---- Rule: very high value + free email = high risk ----
        if total_price > 1000 and is_free_email:
            risk_score += 0.4
            flags.append("very_high_value_free_email")

        # ---- Rule: billing/shipping country mismatch ----
        ship_country = str(shipping_addr.get("country_code", "")).upper()
        bill_country = str(billing_addr.get("country_code", "")).upper()
        if ship_country and bill_country and ship_country != bill_country:
            risk_score += 0.3
            flags.append("billing_shipping_country_mismatch")

        # ---- Rule: extremely high order value ----
        if total_price > 5000:
            risk_score += 0.2
            flags.append("extremely_high_value")

        # ---- Rule: new customer bonus risk ----
        if is_new_customer and total_price > 200:
            risk_score += 0.1
            flags.append("new_customer_moderate_value")

        # ---- Rule: returning customer discount ----
        if orders_count >= 5:
            risk_score = max(0.0, risk_score - 0.2)

        # Clamp score
        risk_score = round(min(max(risk_score, 0.0), 1.0), 2)

        # Classify risk level and recommendation
        if risk_score >= 0.7:
            risk_level = "high"
            recommendation = "reject"
        elif risk_score >= 0.4:
            risk_level = "medium"
            recommendation = "review"
        else:
            risk_level = "low"
            recommendation = "approve"

        return {
            "status": "success",
            "risk_score": risk_score,
            "risk_level": risk_level,
            "recommendation": recommendation,
            "flags": flags,
        }
    except Exception as exc:
        return _fail(f"Fraud screening failed: {exc}")


def _fail(reason: str) -> dict[str, Any]:
    """Return standardized error output."""
    return {
        "status": "error",
        "risk_score": 0.0,
        "risk_level": "unknown",
        "recommendation": "review",
        "flags": [],
        "error": reason,
    }
