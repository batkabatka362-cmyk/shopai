"""Order Quality Engine — defect tracker.

Tracks defects by product and supplier.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def track_defects(
    orders: list[dict[str, Any]],
    defects: list[dict[str, Any]],
    suppliers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Track defect rates by product and supplier.

    Args:
        orders: Order list for total counts.
        defects: Defect records [{order_id, type, severity}].
        suppliers: Supplier list.

    Returns:
        Structured dict with defect rates.
    """
    try:
        # Map orders to suppliers via products
        order_supplier: dict[str, str] = {}
        for order in orders:
            oid = str(order.get("id", order.get("order_id", "")))
            sid = str(order.get("supplier_id", ""))
            if sid:
                order_supplier[oid] = sid

        # Count defects per supplier
        supplier_defects: dict[str, int] = {}
        supplier_orders_count: dict[str, int] = {}
        product_defects: dict[str, int] = {}
        product_orders_count: dict[str, int] = {}

        for order in orders:
            oid = str(order.get("id", order.get("order_id", "")))
            sid = order_supplier.get(oid, str(order.get("supplier_id", "unknown")))
            supplier_orders_count[sid] = supplier_orders_count.get(sid, 0) + 1

            for item in order.get("items", []):
                pid = str(item.get("product_id", ""))
                if pid:
                    product_orders_count[pid] = product_orders_count.get(pid, 0) + 1

        for defect in defects:
            oid = str(defect.get("order_id", ""))
            sid = order_supplier.get(oid, "unknown")
            supplier_defects[sid] = supplier_defects.get(sid, 0) + 1

            pid = str(defect.get("product_id", ""))
            if pid:
                product_defects[pid] = product_defects.get(pid, 0) + 1

        defect_rates: list[dict[str, Any]] = []

        # Supplier defect rates
        for sid, count in supplier_orders_count.items():
            d_count = supplier_defects.get(sid, 0)
            rate = round(d_count / count, 4) if count > 0 else 0.0
            sup = next((s for s in suppliers if str(s.get("id", "")) == sid), {})
            defect_rates.append({
                "entity": str(sup.get("name", sid)),
                "entity_type": "supplier",
                "total_orders": count,
                "defect_count": d_count,
                "defect_rate": rate,
            })

        # Product defect rates
        for pid, count in product_orders_count.items():
            d_count = product_defects.get(pid, 0)
            rate = round(d_count / count, 4) if count > 0 else 0.0
            defect_rates.append({
                "entity": pid,
                "entity_type": "product",
                "total_orders": count,
                "defect_count": d_count,
                "defect_rate": rate,
            })

        return {"status": "success", "defect_rates": defect_rates}
    except Exception as exc:
        return {"status": "error", "defect_rates": [], "error": f"Defect tracking failed: {exc}"}
