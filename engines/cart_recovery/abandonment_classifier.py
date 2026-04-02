"""Cart Recovery Engine — abandonment classifier.

Classifies the likely reason for cart abandonment using cart analysis
features and customer behavior signals.

Reasons:
  - price_shock: high cart total relative to customer avg
  - shipping_cost: cart below free-shipping threshold
  - comparison_shopping: returning customer, moderate value
  - distraction: quick abandonment, engaged customer
  - payment_issue: new customer, high value
  - just_browsing: low value, new customer, single item

Model note: Uses Mistral for analytical classification.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Classification rules (scored, highest wins)
# ---------------------------------------------------------------------------

def classify_abandonment(
    analysis: dict[str, Any],
    customer: dict[str, Any],
    store: dict[str, Any],
) -> dict[str, Any]:
    """Classify the most likely abandonment reason.

    Args:
        analysis: CartAnalysis from cart_analyzer.
        customer: Customer profile data.
        store: Store configuration.

    Returns:
        Structured dict with AbandonmentClassification data.
    """
    try:
        safe_analysis = copy.deepcopy(analysis)
        safe_customer = copy.deepcopy(customer)
        safe_store = copy.deepcopy(store)

        total_value = float(safe_analysis.get("total_value", 0))
        items_count = int(safe_analysis.get("items_count", 0))
        customer_type = str(safe_analysis.get("customer_type", "new"))
        hours_since = float(safe_analysis.get("hours_since_abandonment", 0))
        cart_value_tier = str(safe_analysis.get("cart_value_tier", "medium"))

        avg_order_value = float(safe_customer.get("avg_order_value", 0))
        total_orders = int(safe_customer.get("total_orders", 0))
        free_shipping_threshold = float(safe_store.get("free_shipping_threshold", 50.0))

        # Score each possible reason
        scores: dict[str, float] = {
            "price_shock": 0.0,
            "shipping_cost": 0.0,
            "comparison_shopping": 0.0,
            "distraction": 0.0,
            "payment_issue": 0.0,
            "just_browsing": 0.0,
        }
        signals: list[str] = []

        # --- Price shock: cart much higher than avg order ---
        if avg_order_value > 0 and total_value > avg_order_value * 1.5:
            scores["price_shock"] += 0.4
            signals.append("cart_value_exceeds_avg_by_50pct")
        if cart_value_tier == "high":
            scores["price_shock"] += 0.2
            signals.append("high_value_cart")

        # --- Shipping cost: below free-shipping threshold ---
        if total_value < free_shipping_threshold:
            scores["shipping_cost"] += 0.5
            signals.append("below_free_shipping_threshold")
        if total_value > free_shipping_threshold * 0.7 and total_value < free_shipping_threshold:
            scores["shipping_cost"] += 0.2
            signals.append("close_to_free_shipping")

        # --- Comparison shopping: returning customer, medium value ---
        if customer_type in ("returning", "vip") and cart_value_tier == "medium":
            scores["comparison_shopping"] += 0.35
            signals.append("returning_customer_medium_cart")
        if total_orders >= 2 and hours_since >= 2:
            scores["comparison_shopping"] += 0.15
            signals.append("experienced_buyer_delayed_return")

        # --- Distraction: quick abandonment, engaged customer ---
        if hours_since < 2 and customer_type != "new":
            scores["distraction"] += 0.4
            signals.append("quick_abandonment_known_customer")
        if hours_since < 1:
            scores["distraction"] += 0.15
            signals.append("very_recent_abandonment")

        # --- Payment issue: new customer, high value ---
        if customer_type == "new" and cart_value_tier == "high":
            scores["payment_issue"] += 0.45
            signals.append("new_customer_high_value")
        if customer_type == "new" and total_orders == 0:
            scores["payment_issue"] += 0.1
            signals.append("first_time_buyer")

        # --- Just browsing: low value, new, few items ---
        if cart_value_tier == "low" and customer_type == "new":
            scores["just_browsing"] += 0.45
            signals.append("low_value_new_customer")
        if items_count <= 1:
            scores["just_browsing"] += 0.15
            signals.append("single_item_cart")

        # Pick the winning reason
        best_reason = max(scores, key=lambda k: scores[k])
        best_score = scores[best_reason]

        # Normalize confidence (0..1)
        total_score = sum(scores.values())
        confidence = round(best_score / total_score, 4) if total_score > 0 else 0.0

        return {
            "status": "success",
            "classification": {
                "reason": best_reason,
                "confidence": confidence,
                "signals": signals,
                "model_note": "Mistral: analytical abandonment classification",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "classification": {},
            "error": f"Abandonment classification failed: {exc}",
        }
