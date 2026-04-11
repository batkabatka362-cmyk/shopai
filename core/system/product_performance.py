"""Product Performance Tracker — tracks each product performance over time."""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("product.performance")


class ProductPerformanceTracker:
    """Tracks product scores, rankings, and trends over time."""

    def __init__(self) -> None:
        self._history: dict[str, list[dict]] = {}

    def record(self, products: list[dict], scores: list[dict] | None = None) -> None:
        """Record current product state for trend tracking."""
        now = time.time()
        for p in products:
            pid = str(p.get("id", ""))
            if not pid:
                continue
            entry = {
                "price": float(p.get("price", 0)),
                "inventory": int(p.get("inventory_quantity", 0)),
                "timestamp": now,
            }
            if scores:
                for s in scores:
                    if str(s.get("product_id", "")) == pid:
                        entry["score"] = s.get("total_score", 0)
                        entry["grade"] = s.get("grade", "?")
                        break
            self._history.setdefault(pid, []).append(entry)
            # Keep last 100 entries
            if len(self._history[pid]) > 100:
                self._history[pid] = self._history[pid][-100:]

    def get_trend(self, product_id: str) -> dict[str, Any]:
        """Get performance trend for a product."""
        history = self._history.get(str(product_id), [])
        if len(history) < 2:
            return {"trend": "insufficient_data", "data_points": len(history)}

        prices = [h["price"] for h in history]
        first = sum(prices[:len(prices)//2]) / max(len(prices)//2, 1)
        second = sum(prices[len(prices)//2:]) / max(len(prices) - len(prices)//2, 1)

        if second > first * 1.05:
            price_trend = "increasing"
        elif second < first * 0.95:
            price_trend = "decreasing"
        else:
            price_trend = "stable"

        return {
            "data_points": len(history),
            "price_trend": price_trend,
            "latest_price": prices[-1],
            "latest_inventory": history[-1].get("inventory", 0),
            "latest_grade": history[-1].get("grade", "?"),
        }

    def get_all_trends(self) -> dict[str, dict]:
        result = {}
        for pid in self._history:
            result[pid] = self.get_trend(pid)
        return result

    def get_stats(self) -> dict[str, Any]:
        return {
            "products_tracked": len(self._history),
            "total_records": sum(len(v) for v in self._history.values()),
        }


_instance = None
def get_product_performance():
    global _instance
    if _instance is None:
        _instance = ProductPerformanceTracker()
    return _instance
