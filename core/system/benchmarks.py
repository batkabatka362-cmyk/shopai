"""Performance Benchmarks — compare store to industry standards."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger("benchmark")

# E-commerce industry benchmarks
BENCHMARKS = {
    "conversion_rate": {"good": 0.03, "avg": 0.02, "poor": 0.01},
    "avg_order_value": {"good": 50, "avg": 35, "poor": 20},
    "cart_abandonment": {"good": 0.60, "avg": 0.70, "poor": 0.80},
    "bounce_rate": {"good": 0.35, "avg": 0.45, "poor": 0.60},
    "email_open_rate": {"good": 0.25, "avg": 0.18, "poor": 0.10},
    "gross_margin": {"good": 0.50, "avg": 0.35, "poor": 0.20},
    "products_per_store": {"good": 50, "avg": 25, "poor": 10},
    "customer_acquisition_cost": {"good": 10, "avg": 25, "poor": 50},
    "repeat_purchase_rate": {"good": 0.30, "avg": 0.20, "poor": 0.10},
}


class PerformanceBenchmarks:
    """Compare store metrics to industry benchmarks."""

    def benchmark(self, products: list[dict], orders: list[dict],
                  customers: list[dict]) -> dict[str, Any]:
        """Run benchmark comparison."""
        results = {}

        # Gross margin
        margins = []
        for p in products:
            price = float(p.get("price", 0))
            cost = float(p.get("cost", 0))
            if price > 0 and cost > 0:
                margins.append((price - cost) / price)
        avg_margin = sum(margins) / max(len(margins), 1) if margins else 0
        results["gross_margin"] = self._compare("gross_margin", avg_margin)

        # Products count
        results["products_per_store"] = self._compare(
            "products_per_store", len(products))

        # AOV
        if orders:
            totals = [float(o.get("total_price", o.get("total", 0))) for o in orders]
            aov = sum(totals) / max(len(totals), 1) if totals else 0
            results["avg_order_value"] = self._compare("avg_order_value", aov)

        # Repeat rate
        if customers:
            repeat = sum(1 for c in customers if int(c.get("orders_count", 0)) > 1)
            rate = repeat / max(len(customers), 1)
            results["repeat_purchase_rate"] = self._compare("repeat_purchase_rate", rate)

        # Overall grade
        grades = [r.get("grade", "C") for r in results.values()]
        a_count = grades.count("A")
        overall = "A" if a_count >= len(grades) * 0.6 else "B" if a_count >= len(grades) * 0.3 else "C"

        return {
            "benchmarks": results,
            "overall_grade": overall,
            "strengths": [k for k, v in results.items() if v.get("grade") == "A"],
            "weaknesses": [k for k, v in results.items() if v.get("grade") == "C"],
        }

    @staticmethod
    def _compare(metric: str, value: float) -> dict:
        bench = BENCHMARKS.get(metric, {})
        if value >= bench.get("good", float("inf")):
            grade = "A"
            vs = "above industry average"
        elif value >= bench.get("avg", float("inf")):
            grade = "B"
            vs = "at industry average"
        else:
            grade = "C"
            vs = "below industry average"
        return {
            "value": round(value, 3) if isinstance(value, float) else value,
            "grade": grade,
            "benchmark_good": bench.get("good", 0),
            "benchmark_avg": bench.get("avg", 0),
            "vs_industry": vs,
        }


_instance = None
def get_benchmarks():
    global _instance
    if _instance is None:
        _instance = PerformanceBenchmarks()
    return _instance
