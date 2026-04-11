"""Inventory Engine — stock analyzer.

Analyzes current stock levels per SKU: days-of-stock, turnover rate,
aging score, dead stock identification, and stock status classification.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Stock status thresholds (days of stock remaining)
# ---------------------------------------------------------------------------

_CRITICAL_DAYS = 3
_LOW_DAYS = 7
_HEALTHY_DAYS = 30
# Above HEALTHY_DAYS = overstocked

# Dead stock: if daily_sales_avg is effectively zero
_DEAD_STOCK_SALES_THRESHOLD = 0.01


def analyze_stock(
    products: list[dict[str, Any]],
    warehouse_capacity: int,
) -> dict[str, Any]:
    """Analyze stock levels, turnover, and health for all SKUs.

    Args:
        products: List of ProductInventory dicts.
        warehouse_capacity: Total warehouse capacity in units.

    Returns:
        Structured dict with StockAnalysisResult data.
    """
    try:
        items = copy.deepcopy(products)
        sku_analyses: list[dict[str, Any]] = []

        total_stock = 0
        healthy = 0
        low = 0
        critical = 0
        overstocked = 0
        dead = 0
        turnover_rates: list[float] = []

        for item in items:
            sku_id = str(item.get("id", "unknown"))
            title = str(item.get("title", ""))
            current_stock = int(item.get("current_stock", 0))
            daily_avg = float(item.get("daily_sales_avg", 0.0))

            total_stock += current_stock

            # Days of stock remaining
            if daily_avg > _DEAD_STOCK_SALES_THRESHOLD:
                days_of_stock = round(current_stock / daily_avg, 1)
            else:
                days_of_stock = float("inf")

            # Turnover rate (annualized): how many times stock is sold per year
            if current_stock > 0 and daily_avg > 0:
                turnover_rate = round((daily_avg * 365.0) / current_stock, 2)
            else:
                turnover_rate = 0.0

            # Dead stock detection
            is_dead = daily_avg < _DEAD_STOCK_SALES_THRESHOLD and current_stock > 0

            # Aging score: 0.0 (fresh) to 1.0 (very aged/stale)
            # Based on how many days of stock on hand relative to 90-day benchmark
            if days_of_stock == float("inf"):
                aging_score = 1.0
            else:
                aging_score = round(min(days_of_stock / 90.0, 1.0), 2)

            # Stock status classification
            if is_dead:
                status = "dead_stock"
                dead += 1
            elif days_of_stock <= _CRITICAL_DAYS:
                status = "critical"
                critical += 1
            elif days_of_stock <= _LOW_DAYS:
                status = "low"
                low += 1
            elif days_of_stock <= _HEALTHY_DAYS:
                status = "healthy"
                healthy += 1
            else:
                status = "overstocked"
                overstocked += 1

            if turnover_rate > 0:
                turnover_rates.append(turnover_rate)

            sku_analyses.append({
                "id": sku_id,
                "title": title,
                "current_stock": current_stock,
                "daily_sales_avg": daily_avg,
                "days_of_stock": days_of_stock if days_of_stock != float("inf") else -1,
                "turnover_rate": turnover_rate,
                "stock_status": status,
                "is_dead_stock": is_dead,
                "aging_score": aging_score,
            })

        avg_turnover = (
            round(sum(turnover_rates) / len(turnover_rates), 2)
            if turnover_rates else 0.0
        )

        utilization = (
            round(total_stock / warehouse_capacity, 4)
            if warehouse_capacity > 0 else 0.0
        )

        return {
            "status": "success",
            "analysis": {
                "sku_analyses": sku_analyses,
                "total_skus": len(items),
                "healthy_count": healthy,
                "low_count": low,
                "critical_count": critical,
                "overstocked_count": overstocked,
                "dead_stock_count": dead,
                "avg_turnover_rate": avg_turnover,
                "warehouse_utilization": utilization,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "analysis": {},
            "error": f"Stock analysis failed: {exc}",
        }
