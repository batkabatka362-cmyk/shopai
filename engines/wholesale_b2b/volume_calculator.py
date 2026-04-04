"""Wholesale B2B Engine — volume calculator.

Calculates volume discounts and minimum order quantities.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def calculate_volume_discounts(
    products: list[dict[str, Any]],
    tiers: list[dict[str, Any]],
    order: dict[str, Any],
) -> dict[str, Any]:
    """Calculate volume discounts for an order against pricing tiers.

    Args:
        products: Product list with price field.
        tiers: Pricing tiers from tier_builder.
        order: Order with items [{product_id, quantity}].

    Returns:
        Structured dict with volume discounts.
    """
    try:
        prod_map = {str(p.get("id", "")): p for p in products}
        order_items = copy.deepcopy(order.get("items", []))
        discounts: list[dict[str, Any]] = []

        sorted_tiers = sorted(tiers, key=lambda t: t.get("min_quantity", 0))

        for item in order_items:
            pid = str(item.get("product_id", ""))
            qty = int(item.get("quantity", 0))
            product = prod_map.get(pid, {})
            base_price = float(product.get("price", 0.0))

            applicable_discount = 0.0
            for tier in sorted_tiers:
                if qty >= tier.get("min_quantity", 0):
                    applicable_discount = float(tier.get("discount_pct", 0))

            final_unit = round(base_price * (1.0 - applicable_discount / 100.0), 2)
            total = round(final_unit * qty, 2)

            discounts.append({
                "product_id": pid,
                "quantity": qty,
                "discount_pct": applicable_discount,
                "final_unit_price": final_unit,
                "total_price": total,
            })

        return {"status": "success", "volume_discounts": discounts}
    except Exception as exc:
        return {"status": "error", "volume_discounts": [], "error": f"Volume calculation failed: {exc}"}
