"""Cart Recovery Engine — incentive calculator.

Calculates the optimal incentive to offer for cart recovery, ensuring
the discount stays within safe margins.

Incentive types:
  - percentage: percentage discount on cart total
  - free_shipping: waive shipping cost
  - bundle: bonus item or bundle offer
  - loyalty_points: award loyalty points
  - none: no incentive (for email reminders / urgency)

Model note: no model usage — deterministic margin-safe calculation.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Incentive rules per strategy
# ---------------------------------------------------------------------------

# Base discount percentages by strategy (before margin-safety adjustments)
_BASE_DISCOUNT_PCT: dict[str, float] = {
    "discount_offer": 10.0,
    "free_shipping": 0.0,
    "email_reminder": 0.0,
    "urgency_message": 5.0,
    "retarget_ad": 5.0,
}

# Minimum margin we must preserve (as fraction of cart value)
_MIN_MARGIN_PRESERVE = 0.15

# Max discount cap regardless of margin
_MAX_DISCOUNT_PCT = 25.0


def calculate_incentive(
    strategy: dict[str, Any],
    analysis: dict[str, Any],
    store: dict[str, Any],
) -> dict[str, Any]:
    """Calculate the optimal incentive for cart recovery.

    Args:
        strategy: RecoveryStrategy from strategy selector.
        analysis: CartAnalysis from cart analyzer.
        store: Store configuration (margin, shipping threshold).

    Returns:
        Structured dict with Incentive data and status.
    """
    try:
        safe_strategy = copy.deepcopy(strategy)
        safe_analysis = copy.deepcopy(analysis)
        safe_store = copy.deepcopy(store)

        strategy_name = str(safe_strategy.get("strategy", "email_reminder"))
        priority = str(safe_strategy.get("priority", "medium"))
        total_value = float(safe_analysis.get("total_value", 0))
        cart_value_tier = str(safe_analysis.get("cart_value_tier", "medium"))
        customer_type = str(safe_analysis.get("customer_type", "new"))
        avg_margin = float(safe_store.get("avg_margin", 0.40))
        free_shipping_threshold = float(safe_store.get("free_shipping_threshold", 75.0))

        # --- Free shipping strategy ---
        if strategy_name == "free_shipping":
            return {
                "status": "success",
                "incentive": {
                    "type": "free_shipping",
                    "value": 0,
                    "max_discount_amount": 0.0,
                    "margin_safe": True,
                    "rationale": (
                        f"Free shipping offered — cart ${total_value:.2f} is below "
                        f"threshold ${free_shipping_threshold:.2f}."
                    ),
                },
            }

        # --- Email reminder / no discount needed ---
        if strategy_name == "email_reminder" and priority not in ("high", "critical"):
            return {
                "status": "success",
                "incentive": {
                    "type": "none",
                    "value": 0,
                    "max_discount_amount": 0.0,
                    "margin_safe": True,
                    "rationale": "Simple reminder — no incentive required at this priority level.",
                },
            }

        # --- Loyalty points for VIP customers ---
        if customer_type == "vip" and strategy_name in ("email_reminder", "urgency_message"):
            points_value = round(total_value * 0.05, 2)
            return {
                "status": "success",
                "incentive": {
                    "type": "loyalty_points",
                    "value": points_value,
                    "max_discount_amount": points_value,
                    "margin_safe": True,
                    "rationale": (
                        f"VIP customer offered {points_value} loyalty points "
                        f"(5% of ${total_value:.2f} cart)."
                    ),
                },
            }

        # --- Percentage discount ---
        base_pct = _BASE_DISCOUNT_PCT.get(strategy_name, 5.0)

        # Priority adjustments
        if priority == "critical":
            base_pct += 5.0
        elif priority == "high":
            base_pct += 3.0
        elif priority == "low":
            base_pct = max(base_pct - 2.0, 0.0)

        # Cart value tier adjustments
        if cart_value_tier == "high":
            # Lower percentage on high-value carts (absolute discount is still big)
            base_pct = max(base_pct - 2.0, 5.0)
        elif cart_value_tier == "low":
            # Slightly higher on low-value carts to entice completion
            base_pct += 2.0

        # Cap at maximum
        discount_pct = min(base_pct, _MAX_DISCOUNT_PCT)

        # Margin safety check
        max_discount_amount = round(total_value * (discount_pct / 100.0), 2)
        margin_amount = total_value * avg_margin
        remaining_margin = margin_amount - max_discount_amount
        margin_safe = remaining_margin >= (total_value * _MIN_MARGIN_PRESERVE)

        if not margin_safe:
            # Reduce discount to preserve minimum margin
            safe_discount_amount = margin_amount - (total_value * _MIN_MARGIN_PRESERVE)
            safe_discount_amount = max(safe_discount_amount, 0.0)
            discount_pct = round((safe_discount_amount / total_value) * 100.0, 1) if total_value > 0 else 0.0
            max_discount_amount = round(safe_discount_amount, 2)
            margin_safe = True  # Now it is safe after adjustment

        # Bundle offer for multi-item high-value carts
        items_count = int(safe_analysis.get("items_count", 0))
        if items_count >= 3 and cart_value_tier == "high" and discount_pct < 8:
            return {
                "status": "success",
                "incentive": {
                    "type": "bundle",
                    "value": discount_pct,
                    "max_discount_amount": max_discount_amount,
                    "margin_safe": margin_safe,
                    "rationale": (
                        f"Bundle offer for {items_count}-item high-value cart. "
                        f"Effective discount: {discount_pct}% (${max_discount_amount})."
                    ),
                },
            }

        return {
            "status": "success",
            "incentive": {
                "type": "percentage",
                "value": discount_pct,
                "max_discount_amount": max_discount_amount,
                "margin_safe": margin_safe,
                "rationale": (
                    f"{discount_pct}% discount on ${total_value:.2f} cart "
                    f"(max ${max_discount_amount}). Margin preserved: {margin_safe}."
                ),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "incentive": {},
            "error": f"Incentive calculation failed: {exc}",
        }
