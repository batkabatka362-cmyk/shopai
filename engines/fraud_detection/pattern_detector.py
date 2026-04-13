"""Fraud Detection Engine — pattern detector.

Detects known fraud patterns: card testing (many small orders),
reshipping schemes, gift card abuse, and high-value first orders.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Pattern thresholds
# ---------------------------------------------------------------------------

_CARD_TEST_MAX_AMOUNT = 5.0       # orders under this are potential card tests
_CARD_TEST_MIN_COUNT = 3          # need at least this many small orders
_HIGH_VALUE_FIRST_ORDER = 500.0   # first order above this is suspicious
_GIFT_CARD_HIGH_VALUE = 200.0     # gift card orders above this


def detect_patterns(
    order: dict[str, Any],
    customer: dict[str, Any],
    past_orders: list[dict[str, Any]],
) -> dict[str, Any]:
    """Detect known fraud patterns in order behavior.

    Args:
        order: Current order dict.
        customer: Customer info dict.
        past_orders: Historical orders for this customer/email.

    Returns:
        Structured dict with detected patterns, score, and model note.
    """
    try:
        order = copy.deepcopy(order)
        customer = copy.deepcopy(customer)
        past_orders = copy.deepcopy(past_orders)

        detected: list[str] = []
        risk_points = 0.0
        max_points = 0.0
        notes: list[str] = []

        total_price = float(order.get("total_price", 0.0))
        order_count = int(customer.get("order_count", 0))
        account_age_days = int(customer.get("account_age_days", 0))
        has_gift_card = bool(order.get("has_gift_card", False))

        # ---- 1. Card testing pattern (weight: 3) ----
        max_points += 3.0
        small_orders = [
            p for p in past_orders
            if float(p.get("total_price", 0.0)) <= _CARD_TEST_MAX_AMOUNT
        ]
        current_is_small = total_price <= _CARD_TEST_MAX_AMOUNT

        total_small = len(small_orders) + (1 if current_is_small else 0)
        if total_small >= _CARD_TEST_MIN_COUNT:
            risk_points += 3.0
            detected.append("card_testing")
            notes.append(
                f"Detected {total_small} orders under ${_CARD_TEST_MAX_AMOUNT} "
                f"— possible card validation testing"
            )
        elif total_small >= 2:
            risk_points += 1.0
            notes.append(f"{total_small} small orders — monitoring for card testing")

        # ---- 2. High-value first order (weight: 2.5) ----
        max_points += 2.5
        if order_count == 0 and total_price >= _HIGH_VALUE_FIRST_ORDER:
            risk_points += 2.5
            detected.append("high_value_first_order")
            notes.append(
                f"First order is ${total_price:.2f} — exceeds "
                f"${_HIGH_VALUE_FIRST_ORDER} threshold"
            )
        elif order_count == 0 and total_price >= _HIGH_VALUE_FIRST_ORDER * 0.5:
            risk_points += 1.0
            notes.append("Moderately high first order value")

        # ---- 3. Gift card abuse (weight: 2.5) ----
        max_points += 2.5
        if has_gift_card and total_price >= _GIFT_CARD_HIGH_VALUE:
            risk_points += 2.0
            detected.append("gift_card_abuse")
            notes.append(
                f"Gift card purchase of ${total_price:.2f} — "
                f"above ${_GIFT_CARD_HIGH_VALUE} threshold"
            )
            # Extra risk if new account
            if account_age_days < 7:
                risk_points += 0.5
                notes.append("New account purchasing high-value gift cards")
        elif has_gift_card:
            risk_points += 0.5
            notes.append("Gift card in order — low-value, monitoring")

        # ---- 4. Reshipping pattern (weight: 2) ----
        max_points += 2.0
        # Reshipping: different shipping addresses across recent orders
        if past_orders:
            unique_addresses: set[str] = set()
            for p in past_orders:
                addr = p.get("shipping_address", {})
                key = _address_fingerprint(addr)
                if key:
                    unique_addresses.add(key)

            current_addr = order.get("shipping_address", {})
            current_key = _address_fingerprint(current_addr)
            if current_key:
                unique_addresses.add(current_key)

            address_ratio = (
                len(unique_addresses) / (len(past_orders) + 1)
                if past_orders else 0.0
            )

            if len(unique_addresses) >= 4 and address_ratio > 0.7:
                risk_points += 2.0
                detected.append("reshipping")
                notes.append(
                    f"{len(unique_addresses)} unique shipping addresses "
                    f"across {len(past_orders) + 1} orders — possible reshipping"
                )
            elif len(unique_addresses) >= 3 and address_ratio > 0.5:
                risk_points += 0.8
                notes.append("Multiple shipping addresses — monitoring")

        # ---- 5. Rapid account escalation (weight: 2) ----
        max_points += 2.0
        if account_age_days < 3 and order_count >= 3:
            risk_points += 2.0
            detected.append("rapid_escalation")
            notes.append(
                f"{order_count} orders in {account_age_days} days — "
                f"rapid account escalation"
            )
        elif account_age_days < 7 and order_count >= 5:
            risk_points += 1.5
            detected.append("rapid_escalation")
            notes.append(
                f"{order_count} orders in {account_age_days} days — "
                f"elevated activity for new account"
            )

        # ---- Compute final score ----
        score = round(risk_points / max_points, 4) if max_points > 0 else 0.0
        score = max(0.0, min(1.0, score))

        model_note = "; ".join(notes) if notes else "No suspicious patterns detected"

        return {
            "status": "success",
            "score": score,
            "detected_patterns": detected,
            "model_note": model_note,
        }
    except Exception as exc:
        return {
            "status": "error",
            "score": 0.0,
            "detected_patterns": [],
            "model_note": "",
            "error": f"Pattern detection failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _address_fingerprint(address: dict[str, Any]) -> str:
    """Create a simple fingerprint for an address dict."""
    parts = [
        str(address.get("line1", "")).lower().strip(),
        str(address.get("zip", "")).strip(),
        str(address.get("country", "")).upper().strip(),
    ]
    key = "|".join(parts)
    return key if any(parts) else ""
