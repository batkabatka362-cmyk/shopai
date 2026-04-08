"""Order Management Engine — fraud screener.

Two-track risk assessment for incoming orders:

  1. **Heuristic pre-screen** (always runs) — deterministic
     rules over the order payload (free email + high value,
     billing/shipping country mismatch, new-customer high-value
     ratio, etc.). Cheap, no external calls, useful as a
     fast first filter and as a fallback when no Shopify
     adapter is available.

  2. **Shopify Risk Assessment** (when adapter is wired) —
     calls ``Capability.SHOPIFY_ASSESS_RISK`` via the adapter
     ``SmartRouter``. Returns Shopify's own machine-learning
     score plus its ``recommendation`` (cancel / investigate /
     accept). This is the **authoritative** signal because
     Shopify sees signals we don't (BIN, device fingerprint,
     velocity across the platform, …).

Combination strategy: take the **maximum** of the two scores.
If Shopify says HIGH and the heuristic says LOW, we listen to
Shopify. If the heuristic catches something Shopify missed
(e.g. a brand-new fraud pattern Shopify hasn't trained on yet),
we listen to the heuristic. The result envelope carries both
sources so the operator can see what triggered each signal.

Pre-migration this module ran the heuristic alone and treated
the result as authoritative — that was the cleanup gap that
this migration closes.
"""
from __future__ import annotations

import copy
from typing import Any

from utils.logger import get_logger

logger = get_logger("order_management.fraud")

_FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "aol.com", "mail.com", "protonmail.com", "yandex.com",
    "gmx.com", "zoho.com",
}


def screen_for_fraud(order: dict[str, Any]) -> dict[str, Any]:
    """Run a fraud pre-screen on an order.

    Two-track: heuristic + Shopify adapter (when available).
    See module docstring for the combination strategy.

    Args:
        order: The full order dict. If it carries an ``id`` or
            ``order_id`` field, the Shopify Risk adapter is
            queried in addition to the local heuristic.

    Returns:
        Structured dict with the merged risk assessment. Adds
        a ``shopify_risk`` field when the adapter answered, so
        callers can see both inputs to the combined score.
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

        # Clamp heuristic score
        heuristic_score = round(min(max(risk_score, 0.0), 1.0), 2)

        # ---- Shopify Risk Assessment (when adapter wired) ----
        order_id = order.get("id") or order.get("order_id")
        shopify_risk = _fetch_shopify_risk(order_id) if order_id else None

        # Combine: take the higher of (heuristic, shopify) since
        # Shopify can see signals we can't, but the heuristic
        # can catch new fraud patterns Shopify hasn't trained on.
        combined_score = heuristic_score
        if shopify_risk is not None:
            combined_score = max(heuristic_score, shopify_risk["score"])
            # Promote the Shopify recommendation when it's stricter
            # than what the heuristic would produce on its own.
            if shopify_risk["recommendation"] == "cancel":
                flags.append("shopify_risk_cancel")
            elif shopify_risk["recommendation"] == "investigate":
                flags.append("shopify_risk_investigate")

        combined_score = round(combined_score, 2)

        # Classify risk level and recommendation
        if combined_score >= 0.7:
            risk_level = "high"
            recommendation = "reject"
        elif combined_score >= 0.4:
            risk_level = "medium"
            recommendation = "review"
        else:
            risk_level = "low"
            recommendation = "approve"

        result: dict[str, Any] = {
            "status": "success",
            "risk_score": combined_score,
            "risk_level": risk_level,
            "recommendation": recommendation,
            "flags": flags,
            "heuristic_score": heuristic_score,
        }
        if shopify_risk is not None:
            result["shopify_risk"] = shopify_risk
        return result
    except Exception as exc:
        return _fail(f"Fraud screening failed: {exc}")


def _fetch_shopify_risk(order_id: Any) -> dict[str, Any] | None:
    """Query the Shopify Risk adapter for an authoritative
    assessment.

    Returns ``None`` when the adapter is not available
    (registry empty, no Shopify token configured, vendor
    error). Callers fall back to the heuristic score in that
    case — same behaviour as before this migration landed.
    """
    if not order_id:
        return None

    try:
        from core.adapters import Capability, get_router
    except Exception as exc:  # noqa: BLE001
        logger.debug("adapter import failed: %s", exc)
        return None

    try:
        result = get_router().execute(
            Capability.SHOPIFY_ASSESS_RISK,
            {"order_id": order_id},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("shopify risk adapter raised: %s", exc)
        return None

    if not result.ok:
        return None

    data = result.data or {}
    return {
        "score": float(data.get("score", 0.0) or 0.0),
        "level": data.get("risk_level", "UNKNOWN"),
        "recommendation": data.get("recommendation", "investigate"),
        "facts": data.get("facts", []),
        "protect_eligible": bool(data.get("protect_eligible", False)),
        "adapter": result.adapter,
    }


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
