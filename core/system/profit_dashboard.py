"""Real-time Profit Dashboard — live P&L tracking."""
from __future__ import annotations
from typing import Any


class ProfitDashboard:
    """Live profit tracking per product and store-wide."""

    def generate(self, products, orders=None):
        items = []
        total_revenue = 0
        total_cost = 0

        for p in products:
            price = float(p.get("price", 0))
            cost = float(p.get("cost", 0))
            name = p.get("title", p.get("name", ""))

            shipping = min(price * 0.08, 4.0)
            payment_fee = price * 0.029 + 0.30
            total_item_cost = cost + shipping + payment_fee
            profit = price - total_item_cost

            items.append({
                "name": name[:25],
                "price": round(price, 2),
                "cost": round(cost, 2),
                "fees": round(shipping + payment_fee, 2),
                "profit": round(profit, 2),
                "margin": round(profit / price * 100, 1) if price > 0 else 0,
                "status": "profitable" if profit > 0 else "losing",
            })
            total_revenue += price
            total_cost += total_item_cost

        items.sort(key=lambda x: -x["profit"])
        total_profit = total_revenue - total_cost

        return {
            "products": items,
            "summary": {
                "total_revenue_potential": round(total_revenue, 2),
                "total_costs": round(total_cost, 2),
                "total_profit_potential": round(total_profit, 2),
                "avg_margin": round(total_profit / max(total_revenue, 1) * 100, 1),
                "profitable_count": sum(1 for i in items if i["status"] == "profitable"),
                "losing_count": sum(1 for i in items if i["status"] == "losing"),
            },
        }


_instance = None
def get_profit_dashboard():
    global _instance
    if _instance is None:
        _instance = ProfitDashboard()
    return _instance
