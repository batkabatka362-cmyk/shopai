"""Cart Recovery Engine — cart analyzer.

Analyzes the abandoned cart to extract structured features: total value,
items count, product categories, customer type, time since abandonment,
and cart value tier.

Model note: no model usage — deterministic analysis.
"""
from __future__ import annotations

import copy
import time
from typing import Any


# ---------------------------------------------------------------------------
# Category inference from product titles
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "electronics": ["phone", "laptop", "tablet", "headphone", "speaker", "camera", "charger", "cable"],
    "clothing": ["shirt", "pants", "dress", "jacket", "shoe", "sneaker", "hat", "sock"],
    "beauty": ["cream", "serum", "lipstick", "perfume", "moisturizer", "shampoo", "conditioner"],
    "home": ["pillow", "blanket", "candle", "lamp", "rug", "towel", "curtain", "vase"],
    "food": ["coffee", "tea", "chocolate", "snack", "protein", "vitamin", "supplement"],
    "sports": ["yoga", "dumbbell", "mat", "bottle", "fitness", "running", "gym"],
}

# Value tier thresholds
_LOW_VALUE_THRESHOLD = 30.0
_HIGH_VALUE_THRESHOLD = 100.0


def analyze_cart(
    cart: dict[str, Any],
    customer: dict[str, Any],
) -> dict[str, Any]:
    """Analyze an abandoned cart and customer profile.

    Args:
        cart: Cart data with items, total, abandoned_at.
        customer: Customer profile with order history.

    Returns:
        Structured dict with CartAnalysis data and status.
    """
    try:
        safe_cart = copy.deepcopy(cart)
        safe_customer = copy.deepcopy(customer)

        # --- Total value ---
        total_value = float(safe_cart.get("total", 0.0))
        if total_value <= 0:
            # Recompute from items
            items = safe_cart.get("items", [])
            total_value = sum(
                float(item.get("price", 0)) * int(item.get("quantity", 1))
                for item in items
                if isinstance(item, dict)
            )

        # --- Items count ---
        items = safe_cart.get("items", [])
        items_count = sum(
            int(item.get("quantity", 1))
            for item in items
            if isinstance(item, dict)
        )

        # --- Product categories ---
        product_categories = _infer_categories(items)

        # --- Customer type ---
        total_orders = int(safe_customer.get("total_orders", 0))
        avg_order_value = float(safe_customer.get("avg_order_value", 0.0))
        customer_type = _classify_customer(total_orders, avg_order_value)

        # --- Hours since abandonment ---
        abandoned_at = safe_cart.get("abandoned_at", "")
        hours_since = _compute_hours_since(abandoned_at)

        # --- Cart value tier ---
        if total_value < _LOW_VALUE_THRESHOLD:
            cart_value_tier = "low"
        elif total_value >= _HIGH_VALUE_THRESHOLD:
            cart_value_tier = "high"
        else:
            cart_value_tier = "medium"

        return {
            "status": "success",
            "analysis": {
                "total_value": round(total_value, 2),
                "items_count": items_count,
                "product_categories": product_categories,
                "customer_type": customer_type,
                "hours_since_abandonment": round(hours_since, 2),
                "cart_value_tier": cart_value_tier,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "analysis": {},
            "error": f"Cart analysis failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _infer_categories(items: list[dict[str, Any]]) -> list[str]:
    """Infer product categories from item titles."""
    found: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).lower()
        for category, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw in title for kw in keywords):
                found.add(category)
    if not found:
        found.add("general")
    return sorted(found)


def _classify_customer(total_orders: int, avg_order_value: float) -> str:
    """Classify customer type based on order history."""
    if total_orders == 0:
        return "new"
    if total_orders >= 5 or avg_order_value >= 100.0:
        return "vip"
    return "returning"


def _compute_hours_since(abandoned_at: str) -> float:
    """Compute hours since abandonment from an ISO-8601 timestamp.

    Tolerates Z suffix, +offset, space separator, date-only,
    and fractional seconds. On unparseable input falls back to
    0.0 to preserve downstream expectations (downstream code
    branches on `< N` thresholds) but the robust parser above
    means the fallback is rare. The prior implementation used
    time.strptime with a rigid format + a wrong-on-DST
    time.timezone fixup, which this replaces."""
    if not abandoned_at or not isinstance(abandoned_at, str):
        return 0.0
    try:
        from datetime import datetime, timezone
        s = abandoned_at.strip().replace(" ", "T", 1)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        if len(s) == 10:
            s += "T00:00:00+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = (
            datetime.now(timezone.utc) - dt
        ).total_seconds() / 3600.0
        return max(diff, 0.0)
    except (ValueError, TypeError, OverflowError):
        return 0.0
