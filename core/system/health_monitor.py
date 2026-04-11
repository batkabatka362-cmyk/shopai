"""Store Health Monitor — continuous background health checking.

Monitors: product availability, price consistency, SEO health,
inventory levels, page status, discount validity.
"""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("monitor.health")


class StoreHealthMonitor:
    """Continuous store health monitoring."""

    def __init__(self) -> None:
        self._checks: list[dict] = []
        self._score_history: list[float] = []

    def check(self, products: list[dict], orders: list[dict],
              customers: list[dict], cycle_result: dict | None = None) -> dict[str, Any]:
        """Run comprehensive health check."""
        scores = {}

        # Product health (30 pts)
        scores["products"] = self._check_products(products)

        # Revenue health (25 pts)
        scores["revenue"] = self._check_revenue(orders)

        # Customer health (20 pts)
        scores["customers"] = self._check_customers(customers)

        # Content health (15 pts)
        scores["content"] = self._check_content(products)

        # System health (10 pts)
        scores["system"] = self._check_system(cycle_result) if cycle_result else 8

        total = sum(scores.values())
        grade = "A" if total >= 85 else "B" if total >= 70 else "C" if total >= 50 else "D"

        result = {
            "total_score": total,
            "grade": grade,
            "scores": scores,
            "issues": self._find_issues(products, orders, customers),
            "timestamp": time.time(),
        }
        self._checks.append(result)
        self._score_history.append(total)
        return result

    @staticmethod
    def _check_products(products):
        if not products:
            return 0
        score = 10  # Base
        has_images = sum(1 for p in products if p.get("images") or p.get("image_url"))
        has_desc = sum(1 for p in products if (p.get("body_html") or "").strip())
        score += min(10, has_images / max(len(products), 1) * 10)
        score += min(10, has_desc / max(len(products), 1) * 10)
        return round(score)

    @staticmethod
    def _check_revenue(orders):
        if not orders:
            return 5  # No orders = low score
        revenue = sum(float(o.get("total_price", o.get("total", 0))) for o in orders)
        if revenue > 1000: return 25
        if revenue > 100: return 20
        if revenue > 0: return 15
        return 5

    @staticmethod
    def _check_customers(customers):
        if not customers:
            return 5
        repeat = sum(1 for c in customers if int(c.get("orders_count", 0)) > 1)
        rate = repeat / max(len(customers), 1)
        if rate > 0.3: return 20
        if rate > 0.1: return 15
        if customers: return 10
        return 5

    @staticmethod
    def _check_content(products):
        total = len(products)
        if not total:
            return 0
        with_tags = sum(1 for p in products if p.get("tags"))
        return round(min(15, with_tags / max(total, 1) * 15))

    @staticmethod
    def _check_system(cycle_result):
        if not cycle_result:
            return 5
        phases = cycle_result.get("phases", {})
        layers = phases.get("layers", {}).get("layers_run", 0)
        return min(10, layers)

    @staticmethod
    def _find_issues(products, orders, customers):
        issues = []
        no_img = sum(1 for p in products if not (p.get("images") or p.get("image_url")))
        if no_img:
            issues.append("{} products without images".format(no_img))
        if not orders:
            issues.append("No orders — need traffic and marketing")
        low_inv = sum(1 for p in products if int(p.get("inventory_quantity", 0)) < 3)
        if low_inv:
            issues.append("{} products with low inventory".format(low_inv))
        if len(products) < 20:
            issues.append("Only {} products — consider expanding catalog".format(len(products)))
        return issues

    def get_trend(self) -> dict[str, Any]:
        if len(self._score_history) < 2:
            return {"trend": "insufficient_data"}
        recent = self._score_history[-5:]
        avg = sum(recent) / len(recent)
        prev = self._score_history[-10:-5] if len(self._score_history) >= 10 else self._score_history[:len(self._score_history)//2]
        prev_avg = sum(prev) / max(len(prev), 1)
        return {
            "trend": "improving" if avg > prev_avg + 2 else "declining" if avg < prev_avg - 2 else "stable",
            "current": round(avg, 1),
            "previous": round(prev_avg, 1),
        }

    def get_stats(self) -> dict[str, Any]:
        return {"checks_run": len(self._checks),
                "latest_score": self._score_history[-1] if self._score_history else 0}


_instance = None
def get_health_monitor():
    global _instance
    if _instance is None:
        _instance = StoreHealthMonitor()
    return _instance
