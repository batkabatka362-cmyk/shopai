"""Inventory Predictor — predict stockouts and reorder timing."""
from __future__ import annotations
import threading as _threading


class InventoryPredictor:
    """Predicts when products will run out and when to reorder."""

    def predict_all(self, products, daily_sales_estimate=0.5):
        predictions = []
        for p in products:
            inv = int(p.get("inventory_quantity", 0))
            name = p.get("title", p.get("name", ""))
            price = float(p.get("price", 0))

            if inv <= 0:
                predictions.append({"name": name[:25], "status": "OUT_OF_STOCK",
                    "days_until_stockout": 0, "action": "REORDER NOW"})
                continue

            days_left = inv / max(daily_sales_estimate, 0.1)
            lead_time = 14  # days for supplier

            if days_left < lead_time:
                action = "REORDER NOW"
                urgency = "critical"
            elif days_left < lead_time * 2:
                action = "REORDER SOON"
                urgency = "warning"
            else:
                action = "OK"
                urgency = "normal"

            predictions.append({
                "name": name[:25], "inventory": inv,
                "daily_est": daily_sales_estimate,
                "days_until_stockout": round(days_left),
                "reorder_by": round(max(0, days_left - lead_time)),
                "action": action, "urgency": urgency,
                "revenue_at_risk": round(price * inv, 2),
            })

        predictions.sort(key=lambda x: x.get("days_until_stockout", 999))
        critical = sum(1 for p in predictions if p.get("urgency") == "critical")

        return {"predictions": predictions, "total": len(predictions),
                "critical": critical,
                "total_revenue_at_risk": round(sum(p.get("revenue_at_risk",0) for p in predictions), 2)}


_instance = None
_instance_lock = _threading.Lock()

def get_inventory_predictor():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = InventoryPredictor()
    return _instance
