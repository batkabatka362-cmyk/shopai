"""Cross-Sell Engine — purchase analyzer.

Analyzes purchase history and current cart to extract structured features:
frequent product combos, category preferences, price ranges, and timing signals.

Model note: no model usage — deterministic analysis.
"""
from __future__ import annotations

import copy
from collections import Counter
from itertools import combinations
from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_purchases(
    current_cart: list[dict[str, Any]],
    customer: dict[str, Any],
    catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze cart and purchase history for cross-sell signals.

    Args:
        current_cart: List of products currently in the cart.
        customer: Customer profile with past_purchases and preferences.
        catalog: Full product catalog.

    Returns:
        Structured dict with PurchaseAnalysis data and status.
    """
    try:
        safe_cart = copy.deepcopy(current_cart)
        safe_customer = copy.deepcopy(customer)

        past_purchases = safe_customer.get("past_purchases", [])
        preferences = safe_customer.get("preferences", [])

        # --- Cart basics ---
        cart_product_ids = [
            str(item.get("product_id", ""))
            for item in safe_cart
            if isinstance(item, dict) and item.get("product_id")
        ]
        cart_categories = list({
            str(item.get("category", "general"))
            for item in safe_cart
            if isinstance(item, dict)
        })
        total_cart_value = sum(
            float(item.get("price", 0))
            for item in safe_cart
            if isinstance(item, dict)
        )

        # --- Frequent combos from past purchases ---
        # Build "baskets" — group past purchases by category to find
        # which product_ids were bought together (using category as proxy
        # when we lack transaction-level grouping)
        past_ids = [
            str(p.get("product_id", ""))
            for p in past_purchases
            if isinstance(p, dict) and p.get("product_id")
        ]
        # All pairs of (cart_item, past_purchase) as potential combos
        frequent_combos: list[list[str]] = []
        combo_counts: Counter[tuple[str, str]] = Counter()
        for cart_id in cart_product_ids:
            for past_id in past_ids:
                if cart_id != past_id:
                    pair = tuple(sorted([cart_id, past_id]))
                    combo_counts[pair] += 1
        # Take top combos that appear more than once or just the top pairs
        for pair, count in combo_counts.most_common(20):
            frequent_combos.append(list(pair))

        # --- Category preferences ---
        category_counter: Counter[str] = Counter()
        for p in past_purchases:
            if isinstance(p, dict):
                cat = str(p.get("category", "general"))
                category_counter[cat] += 1
        # Normalize to 0-1 affinity scores
        total_cats = sum(category_counter.values()) or 1
        category_preferences: dict[str, float] = {
            cat: round(count / total_cats, 4)
            for cat, count in category_counter.most_common(20)
        }
        # Boost preferred categories from explicit preferences
        for pref in preferences:
            pref_lower = str(pref).lower()
            for cat in category_preferences:
                if pref_lower in cat.lower() or cat.lower() in pref_lower:
                    category_preferences[cat] = min(
                        round(category_preferences[cat] * 1.3, 4), 1.0
                    )

        # --- Price range from cart ---
        prices = [
            float(item.get("price", 0))
            for item in safe_cart
            if isinstance(item, dict) and item.get("price")
        ]
        if prices:
            price_range = {
                "min": round(min(prices), 2),
                "max": round(max(prices), 2),
                "avg": round(sum(prices) / len(prices), 2),
            }
        else:
            price_range = {"min": 0.0, "max": 0.0, "avg": 0.0}

        # --- Timing signals ---
        timing_signals: dict[str, Any] = {
            "cart_size": len(safe_cart),
            "past_purchase_count": len(past_purchases),
            "has_preferences": len(preferences) > 0,
            "repeat_category_buyer": any(
                cat in category_preferences for cat in cart_categories
            ),
        }

        return {
            "status": "success",
            "analysis": {
                "frequent_combos": frequent_combos,
                "category_preferences": category_preferences,
                "price_range": price_range,
                "cart_categories": cart_categories,
                "cart_product_ids": cart_product_ids,
                "total_cart_value": round(total_cart_value, 2),
                "timing_signals": timing_signals,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "analysis": {},
            "error": f"Purchase analysis failed: {exc}",
        }
