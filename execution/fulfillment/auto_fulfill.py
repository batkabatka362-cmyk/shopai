"""Order Fulfillment Automation — manages order processing pipeline.

Automates: order validation, inventory check, shipping estimate,
fulfillment routing, and status tracking.
"""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("fulfillment.auto")


class FulfillmentAutomation:
    """Automated order fulfillment pipeline."""

    def __init__(self) -> None:
        self._processed: list[dict] = []

    def process_orders(self, orders: list[dict],
                       products: list[dict]) -> dict[str, Any]:
        """Process pending orders through fulfillment pipeline."""
        if not orders:
            return {"status": "no_orders", "processed": 0}

        inventory = {str(p.get("id", "")): int(p.get("inventory_quantity", 0))
                     for p in products}
        results = []

        for order in orders:
            result = self._process_order(order, inventory)
            results.append(result)
            self._processed.append(result)

        fulfillable = sum(1 for r in results if r["status"] == "fulfillable")
        return {
            "total_orders": len(orders),
            "fulfillable": fulfillable,
            "blocked": len(results) - fulfillable,
            "results": results[:10],
        }

    def _process_order(self, order: dict, inventory: dict) -> dict[str, Any]:
        oid = str(order.get("id", order.get("order_number", "")))
        total = float(order.get("total_price", order.get("total", 0)))
        status = order.get("financial_status", order.get("status", "pending"))

        # Step 1: Validate
        if status not in ("paid", "authorized", "complete"):
            return {"order_id": oid, "status": "awaiting_payment", "reason": status}

        # Step 2: Check inventory
        items = order.get("line_items", order.get("items", []))
        if not isinstance(items, list):
            items = []
        out_of_stock = []
        for item in items:
            if isinstance(item, dict):
                pid = str(item.get("product_id", ""))
                qty = int(item.get("quantity", 1))
                avail = inventory.get(pid, 0)
                if avail < qty:
                    out_of_stock.append(pid)

        if out_of_stock:
            return {"order_id": oid, "status": "blocked",
                    "reason": "out_of_stock", "products": out_of_stock}

        # Step 3: Estimate shipping
        shipping_est = self._estimate_shipping(order)

        # Step 4: Route
        return {
            "order_id": oid,
            "status": "fulfillable",
            "total": total,
            "shipping_days": shipping_est,
            "action": "ship",
        }

    @staticmethod
    def _estimate_shipping(order: dict) -> int:
        country = ""
        addr = order.get("shipping_address", {})
        if isinstance(addr, dict):
            country = addr.get("country_code", addr.get("country", "US"))
        if country in ("US", "CA"):
            return 3
        elif country in ("GB", "AU", "DE", "FR"):
            return 7
        return 10

    def get_stats(self) -> dict[str, Any]:
        fulfillable = sum(1 for r in self._processed if r.get("status") == "fulfillable")
        return {"processed": len(self._processed), "fulfillable": fulfillable}


_instance = None
def get_fulfillment():
    global _instance
    if _instance is None:
        _instance = FulfillmentAutomation()
    return _instance
