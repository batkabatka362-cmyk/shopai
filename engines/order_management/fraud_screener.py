"""Order Management Engine — fraud screener.

Quick risk pre-screen for orders. NOT the full fraud_detection engine —
this is a fast heuristic pass that runs inline during order processing.

All scoring is deterministic and rule-based.
"""
from __future__ import annotations

import copy
from typing import Any

# Free / disposable email domains used for risk scoring
_FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "aol.com", "mail.com", "protonmail.com", "yandex.com",
    "gmx.com", "icloud.com",
}


def screen_for_fraud(order: dict[str, Any]) -> dict[str, Any]:
    """Run a quick fraud pre-screen on an order.

    Args:
        order: Order dict with customer, billing, shipping info.

    Returns:
        Structured dict with risk score, level, recommendation, and flags.
    """
    try:
        order = copy.deepcopy(order)
        flags: list[str] = []
        risk_score = 0.0

        total_price = float(order.get("total_price", 0))
        customer = order.get("customer", {}) or {}
        email = str(order.get("email", ""))
        orders_count = int(customer.get("orders_count", 0))
        shipping_addr = order.get("shipping_address", {}) or {}
        billing_addr = order.get("billing_address", {}) or {}

        # --- Flag: new customer ---
        is_new_customer = orders_count == 0
        if is_new_customer:
            flags.append("new_customer")
            risk_score += 0.1

        # --- Flag: free email domain ---
        email_domain = email.split("@")[-1].lower() if "@" in email else ""
        is_free_email = email_domain in _FREE_EMAIL_DOMAINS
        if is_free_email:
            flags.append("free_email_domain")
            risk_score += 0.05

        # --- Flag: high amount + new customer ---
        if total_price > 500 and is_new_customer:
            flags.append("high_amount_new_customer")
            risk_score += 0.25

        # --- Flag: very high amount + free email ---
        if total_price > 1000 and is_free_email:
            flags.append("very_high_amount_free_email")
            risk_score += 0.35

        # --- Flag: billing/shipping country mismatch ---
        shipping_country = str(shipping_addr.get("country_code", "")).upper()
        billing_country = str(billing_addr.get("country_code", "")).upper()
        if (
            shipping_country
            and billing_country
            and shipping_country != billing_country
        ):
            flags.append("billing_shipping_country_mismatch")
            risk_score += 0.3

        # --- Flag: very large order amount ---
        if total_price > 2000:
            flags.append("unusually_large_order")
            risk_score += 0.15

        # --- Clamp score ---
        risk_score = round(min(risk_score, 1.0), 2)

        # --- Risk level and recommendation ---
        if risk_score >= 0.7:
            risk_level = "high"
            recommendation = "reject"
        elif risk_score >= 0.3:
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
        return {
            "status": "error",
            "risk_score": 0.0,
            "risk_level": "unknown",
            "recommendation": "review",
            "flags": [],
            "error": f"Fraud screening failed: {exc}",
        }
