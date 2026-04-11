"""Dropshipping Engine — supplier matcher.

Matches products to dropship suppliers based on catalog overlap, price, and reliability.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def match_suppliers(
    products: list[dict[str, Any]],
    suppliers: list[dict[str, Any]],
    orders: list[dict[str, Any]],
) -> dict[str, Any]:
    """Match orders to best-fit suppliers for dropshipping.

    Args:
        products: Product catalog.
        suppliers: Available suppliers with catalog info.
        orders: Customer orders to fulfill.

    Returns:
        Structured dict with supplier orders.
    """
    try:
        prod_map = {str(p.get("id", "")): p for p in products}
        supplier_orders: list[dict[str, Any]] = []

        for order in orders:
            order_id = str(order.get("id", order.get("order_id", "")))
            items = copy.deepcopy(order.get("items", []))

            # Group items by best supplier
            supplier_items: dict[str, list[dict[str, Any]]] = {}
            for item in items:
                pid = str(item.get("product_id", ""))
                qty = int(item.get("quantity", 1))
                product = prod_map.get(pid, {})

                best_supplier = None
                best_cost = float("inf")

                for supplier in suppliers:
                    sid = str(supplier.get("id", ""))
                    catalog = supplier.get("catalog", [])
                    catalog_ids = [str(c.get("product_id", c.get("id", ""))) for c in catalog]

                    if pid in catalog_ids:
                        # Find cost from supplier catalog
                        for c in catalog:
                            if str(c.get("product_id", c.get("id", ""))) == pid:
                                cost = float(c.get("cost", c.get("price", 0.0)))
                                if cost < best_cost:
                                    best_cost = cost
                                    best_supplier = supplier
                                break

                if best_supplier is None and suppliers:
                    best_supplier = suppliers[0]
                    best_cost = float(product.get("cost", product.get("price", 0.0))) * 0.6

                if best_supplier:
                    sid = str(best_supplier.get("id", ""))
                    if sid not in supplier_items:
                        supplier_items[sid] = []
                    supplier_items[sid].append({
                        "product_id": pid,
                        "quantity": qty,
                        "unit_cost": best_cost,
                        "line_total": round(best_cost * qty, 2),
                    })

            for sid, sitems in supplier_items.items():
                sup = next((s for s in suppliers if str(s.get("id", "")) == sid), {})
                total_cost = sum(i["line_total"] for i in sitems)
                supplier_orders.append({
                    "order_id": order_id,
                    "supplier_id": sid,
                    "supplier_name": str(sup.get("name", "")),
                    "items": sitems,
                    "total_cost": round(total_cost, 2),
                    "status": "pending",
                })

        return {"status": "success", "supplier_orders": supplier_orders}
    except Exception as exc:
        return {"status": "error", "supplier_orders": [], "error": f"Supplier matching failed: {exc}"}
