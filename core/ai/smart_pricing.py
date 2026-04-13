"""Smart Pricing Engine — dynamic pricing with competitor awareness."""
from __future__ import annotations
import threading as _threading
from typing import Any
from utils.logger import get_logger
logger = get_logger("pricing.smart")


class SmartPricingEngine:
    """Dynamic pricing based on competition, demand, time, stock."""

    def optimize_prices(self, products, competitor_prices=None, time_context=None):
        """Recommend price adjustments per product.

        competitor_prices: optional {product_id: avg_competitor_price}
        time_context: optional dict with is_weekend for premium pricing
        """
        comp = competitor_prices or {}
        results = []
        for p in products:
            price = float(p.get("price", 0))
            cost = float(p.get("cost", 0))
            inv = int(p.get("inventory_quantity", 0))
            pid = str(p.get("id", ""))
            if price <= 0:
                continue

            from utils.finance import margin as _margin
            margin = _margin(price, cost, default=0.5)
            rec = {"product_id": pid, "current": price, "action": "keep", "reason": ""}

            comp_price = float(comp.get(pid, 0) or 0)
            if comp_price > 0:
                diff_pct = (price - comp_price) / comp_price
                if diff_pct > 0.15:
                    rec["action"] = "lower"
                    rec["new_price"] = round(comp_price * 1.05, 2)
                    rec["reason"] = "Priced {:.0%} above competitor ${}".format(diff_pct, comp_price)
                elif diff_pct < -0.15 and margin > 0.3:
                    rec["action"] = "raise"
                    rec["new_price"] = round(comp_price * 0.95, 2)
                    rec["reason"] = "Priced {:.0%} below competitor ${}".format(-diff_pct, comp_price)

            if rec["action"] == "keep":
                if 0 < inv < 5:
                    rec["action"] = "raise"
                    rec["new_price"] = round(price * 1.1, 2)
                    rec["reason"] = "Low stock ({}) — increase margin".format(inv)
                elif inv > 50 and margin > 0.4:
                    rec["action"] = "lower"
                    rec["new_price"] = round(price * 0.95, 2)
                    rec["reason"] = "High stock ({}) — drive volume".format(inv)
                elif margin < 0.2 and cost > 0:
                    rec["action"] = "raise"
                    rec["new_price"] = round(cost * 1.5, 2)
                    rec["reason"] = "Margin too low ({:.0%})".format(margin)
                else:
                    rec["reason"] = "Price optimal (margin {:.0%})".format(margin)

            if time_context and time_context.get("is_weekend"):
                if rec["action"] == "keep" and margin > 0.3:
                    rec["action"] = "raise"
                    rec["new_price"] = round(price * 1.05, 2)
                    rec["reason"] += " + weekend premium"

            results.append(rec)

        return {"recommendations": results,
                "raise": sum(1 for r in results if r["action"]=="raise"),
                "lower": sum(1 for r in results if r["action"]=="lower"),
                "keep": sum(1 for r in results if r["action"]=="keep")}


_instance = None
_instance_lock = _threading.Lock()

def get_smart_pricing():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SmartPricingEngine()
    return _instance
