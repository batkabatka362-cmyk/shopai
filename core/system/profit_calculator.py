"""Profit Calculator — real P&L per product and store-wide."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger("finance.profit")


class ProfitCalculator:
    """Calculates real profit per product and store-wide P&L."""

    def calculate_product(self, product: dict, orders: list[dict] | None = None) -> dict[str, Any]:
        price = float(product.get("price", 0))
        cost = float(product.get("cost", 0))
        pid = str(product.get("id", ""))
        name = product.get("name", product.get("title", ""))

        if price <= 0:
            return {"product_id": pid, "name": name, "status": "no_price"}

        # Direct costs
        cogs = cost
        shipping_est = min(price * 0.1, 5.0)  # ~10% or max $5
        payment_fee = price * 0.029 + 0.30  # Stripe/Shopify Payments
        platform_fee = 0  # Shopify plan covers this

        total_cost = cogs + shipping_est + payment_fee
        gross_profit = price - total_cost
        margin = gross_profit / price if price > 0 else 0

        # Revenue from orders
        units_sold = 0
        total_revenue = 0
        if orders:
            for o in orders:
                items = o.get("line_items", [])
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict) and str(item.get("product_id", "")) == pid:
                            qty = int(item.get("quantity", 1))
                            units_sold += qty
                            total_revenue += float(item.get("price", price)) * qty

        return {
            "product_id": pid,
            "name": name[:30],
            "price": round(price, 2),
            "cogs": round(cogs, 2),
            "shipping": round(shipping_est, 2),
            "payment_fee": round(payment_fee, 2),
            "total_cost": round(total_cost, 2),
            "gross_profit": round(gross_profit, 2),
            "margin": round(margin * 100, 1),
            "units_sold": units_sold,
            "total_revenue": round(total_revenue, 2),
            "total_profit": round(gross_profit * units_sold, 2),
            "profitable": gross_profit > 0,
        }

    def calculate_store(self, products: list[dict],
                        orders: list[dict] | None = None) -> dict[str, Any]:
        results = [self.calculate_product(p, orders) for p in products]
        profitable = [r for r in results if r.get("profitable")]
        unprofitable = [r for r in results if not r.get("profitable") and r.get("status") != "no_price"]

        total_potential_profit = sum(r.get("gross_profit", 0) for r in results)
        total_actual_profit = sum(r.get("total_profit", 0) for r in results)
        total_revenue = sum(r.get("total_revenue", 0) for r in results)
        avg_margin = sum(r.get("margin", 0) for r in results) / max(len(results), 1)

        return {
            "products": len(results),
            "profitable": len(profitable),
            "unprofitable": len(unprofitable),
            "avg_margin": round(avg_margin, 1),
            "total_potential_profit_per_sale": round(total_potential_profit, 2),
            "total_actual_profit": round(total_actual_profit, 2),
            "total_revenue": round(total_revenue, 2),
            "top_profitable": sorted(results, key=lambda x: -x.get("gross_profit", 0))[:5],
            "needs_attention": [r for r in results if r.get("margin", 0) < 20],
        }


_instance = None
def get_profit_calculator():
    global _instance
    if _instance is None:
        _instance = ProfitCalculator()
    return _instance
