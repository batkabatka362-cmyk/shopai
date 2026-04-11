"""Fraud Detection Engine — base risk scorer.

Computes a baseline risk score (0.0-1.0) from order and customer attributes:
order amount vs customer average, email domain quality, customer age,
and historical order count.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Free email providers (higher risk for high-value orders)
# ---------------------------------------------------------------------------

_FREE_EMAIL_DOMAINS: set[str] = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "mail.com", "protonmail.com", "icloud.com", "yandex.com", "zoho.com",
    "gmx.com", "live.com", "inbox.com", "fastmail.com", "tutanota.com",
}

# Disposable email domains (very high risk)
_DISPOSABLE_EMAIL_DOMAINS: set[str] = {
    "mailinator.com", "guerrillamail.com", "tempmail.com", "throwaway.email",
    "sharklasers.com", "guerrillamailblock.com", "grr.la", "dispostable.com",
    "yopmail.com", "trashmail.com", "fakeinbox.com", "maildrop.cc",
}


def score_base_risk(
    order: dict[str, Any],
    customer: dict[str, Any],
) -> dict[str, Any]:
    """Score baseline fraud risk from order and customer attributes.

    Args:
        order: Order data dict.
        customer: Customer info dict.

    Returns:
        Structured dict with score and contributing factors.
    """
    try:
        order = copy.deepcopy(order)
        customer = copy.deepcopy(customer)

        factors: list[str] = []
        risk_points = 0.0
        max_points = 0.0

        # ---- 1. Order amount vs customer average (weight: 3) ----
        max_points += 3.0
        total_price = float(order.get("total_price", 0.0))
        avg_order_value = float(customer.get("avg_order_value", 0.0))

        if avg_order_value > 0:
            amount_ratio = total_price / avg_order_value
            if amount_ratio > 5.0:
                risk_points += 3.0
                factors.append("order_amount_5x_above_average")
            elif amount_ratio > 3.0:
                risk_points += 2.0
                factors.append("order_amount_3x_above_average")
            elif amount_ratio > 2.0:
                risk_points += 1.0
                factors.append("order_amount_2x_above_average")
            else:
                factors.append("moderate_amount")
        else:
            # No purchase history — first order
            if total_price > 500.0:
                risk_points += 2.5
                factors.append("high_value_first_purchase")
            elif total_price > 200.0:
                risk_points += 1.5
                factors.append("moderate_value_first_purchase")
            else:
                risk_points += 0.5
                factors.append("low_value_first_purchase")

        # ---- 2. Email domain quality (weight: 2) ----
        max_points += 2.0
        email = str(order.get("email", customer.get("email", ""))).lower()
        domain = email.split("@")[-1] if "@" in email else ""

        if domain in _DISPOSABLE_EMAIL_DOMAINS:
            risk_points += 2.0
            factors.append("disposable_email")
        elif domain in _FREE_EMAIL_DOMAINS:
            risk_points += 0.5
            factors.append("free_email_provider")
        elif domain:
            factors.append("corporate_email")
        else:
            risk_points += 1.5
            factors.append("missing_email")

        # ---- 3. Customer account age (weight: 2.5) ----
        max_points += 2.5
        account_age_days = int(customer.get("account_age_days", 0))

        if account_age_days < 1:
            risk_points += 2.5
            factors.append("guest_or_brand_new_account")
        elif account_age_days < 7:
            risk_points += 2.0
            factors.append("account_under_7_days")
        elif account_age_days < 30:
            risk_points += 1.0
            factors.append("account_under_30_days")
        elif account_age_days < 90:
            risk_points += 0.5
            factors.append("account_under_90_days")
        else:
            factors.append("established_customer")

        # ---- 4. Historical order count (weight: 2.5) ----
        max_points += 2.5
        order_count = int(customer.get("order_count", 0))

        if order_count == 0:
            risk_points += 2.5
            factors.append("no_order_history")
        elif order_count < 3:
            risk_points += 1.5
            factors.append("few_prior_orders")
        elif order_count < 10:
            risk_points += 0.5
            factors.append("some_order_history")
        else:
            factors.append("extensive_order_history")

        # ---- Compute final score ----
        score = round(risk_points / max_points, 4) if max_points > 0 else 0.0
        score = max(0.0, min(1.0, score))

        return {
            "status": "success",
            "score": score,
            "factors": factors,
        }
    except Exception as exc:
        return {
            "status": "error",
            "score": 0.0,
            "factors": [],
            "error": f"Base risk scoring failed: {exc}",
        }
