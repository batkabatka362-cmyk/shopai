"""Smart Pricing Engine — dynamic pricing with competitor awareness."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger("pricing.smart")


class SmartPricingEngine:
    """Dynamic pricing based on competition, demand, time, stock."""

    def optimize_prices(self, products, competitor_prices=None, time_context=None):
        results = []
        for p in products:
            price = float(p.get("price", 0))
            cost = float(p.get("cost", 0))
            inv = int(p.get("inventory_quantity", 0))
            if price <= 0:
                continue

            margin = (price - cost) / price if cost > 0 else 0.5
            rec = {"product_id": str(p.get("id","")), "current": price, "action": "keep", "reason": ""}

            # Low stock + selling = raise price
            if inv < 5 and inv > 0:
                rec["action"] = "raise"
                rec["new_price"] = round(price * 1.1, 2)
                rec["reason"] = "Low stock ({}) — increase margin".format(inv)
            # High stock = consider discount
            elif inv > 50 and margin > 0.4:
                rec["action"] = "lower"
                rec["new_price"] = round(price * 0.95, 2)
                rec["reason"] = "High stock ({}) — drive volume".format(inv)
            # Low margin = raise
            elif margin < 0.2 and cost > 0:
                rec["action"] = "raise"
                rec["new_price"] = round(cost * 1.5, 2)
                rec["reason"] = "Margin too low ({:.0%})".format(margin)
            else:
                rec["reason"] = "Price optimal (margin {:.0%})".format(margin)

            # Weekend boost
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
def get_smart_pricing():
    global _instance
    if _instance is None:
        _instance = SmartPricingEngine()
    return _instance
