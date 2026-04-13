"""Dead stock detection — inventory aging that ties up capital."""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("intelligence.supply.dead_stock")

# Dead stock aging tiers
DEAD_STOCK_TIERS = [
    {"days": 90, "label": "slow_moving", "action": "Bundle with fast movers or run 20% discount"},
    {"days": 120, "label": "at_risk", "action": "Run 40% clearance sale, consider liquidation"},
    {"days": 180, "label": "dead_stock", "action": "Liquidate at cost or donate for tax write-off"},
    {"days": 365, "label": "write_off", "action": "Write off inventory, stop reordering"},
]


def detect_dead_stock(
    products: list[dict[str, Any]],
    orders: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Detect dead stock — inventory aging that ties up capital."""
    if not products:
        return {"status": "no_data"}

    # Track which products have sold recently
    sold_products = set()
    if orders:
        for order in orders:
            if not isinstance(order, dict):
                continue
            for item in order.get("line_items", []):
                if isinstance(item, dict):
                    sold_products.add(str(item.get("product_id", "")))

    results = []
    total_dead_value = 0

    for product in products:
        if not isinstance(product, dict):
            continue

        pid = str(product.get("id", ""))
        name = product.get("title", product.get("name", f"Product {pid}"))
        stock = safe_int(product.get("inventory_quantity", 0))
        cost = safe_float(product.get("cost", 0))
        price = safe_float(product.get("price", 0))
        days_since_last_sale = safe_int(product.get("days_since_last_sale", 0))

        if pid not in sold_products and stock > 0:
            days_since_last_sale = max(days_since_last_sale, 30)

        if stock <= 0 or days_since_last_sale < 30:
            continue

        # Determine aging tier
        tier_label = "active"
        tier_action = "Monitor"
        for tier in DEAD_STOCK_TIERS:
            if days_since_last_sale >= tier["days"]:
                tier_label = tier["label"]
                tier_action = tier["action"]

        if tier_label == "active":
            continue

        inventory_value = round(stock * cost, 2)
        total_dead_value += inventory_value

        results.append({
            "product": name,
            "product_id": pid,
            "stock": stock,
            "days_since_sale": days_since_last_sale,
            "tier": tier_label,
            "inventory_value": inventory_value,
            "retail_value": round(stock * price, 2),
            "action": tier_action,
        })

    results.sort(key=lambda r: r["inventory_value"], reverse=True)

    return {
        "dead_stock_items": len(results),
        "total_capital_tied_up": round(total_dead_value, 2),
        "details": results[:20],
        "recommendation": (
            f"${total_dead_value:,.0f} tied up in dead stock. "
            "Bundle slow movers with fast sellers, or run clearance."
            if total_dead_value > 0 else "No significant dead stock detected."
        ),
    }
