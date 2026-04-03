"""Stock Prediction Engine — seasonality detector.

Detects seasonal patterns from order history data by analyzing
monthly distribution of orders per product.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Default retail seasonality (used when insufficient data)
# ---------------------------------------------------------------------------

_DEFAULT_SEASONAL_INDEX: dict[str, float] = {
    "01": 0.80, "02": 0.82, "03": 0.90, "04": 0.95,
    "05": 1.00, "06": 1.02, "07": 1.00, "08": 0.98,
    "09": 1.05, "10": 1.08, "11": 1.25, "12": 1.35,
}


def detect_seasonality(
    orders_history: list[dict[str, Any]],
    demand_models: list[dict[str, Any]],
) -> dict[str, Any]:
    """Detect seasonal patterns per product from order history.

    Args:
        orders_history: List of OrderHistory dicts with date field.
        demand_models: List of DemandModel dicts from demand_modeler.

    Returns:
        Structured dict with per-product seasonal factors.
    """
    try:
        orders = copy.deepcopy(orders_history)

        # Build per-product monthly order counts
        product_monthly: dict[str, dict[str, int]] = {}
        for order in orders:
            pid = str(order.get("product_id", ""))
            date_str = str(order.get("date", ""))
            if not pid or len(date_str) < 7:
                continue
            month = date_str[5:7]  # "YYYY-MM-DD" -> "MM"
            product_monthly.setdefault(pid, {})
            product_monthly[pid][month] = product_monthly[pid].get(month, 0) + 1

        # Extract unique product IDs from demand models
        product_ids = [str(m.get("product_id", "")) for m in demand_models]

        seasonal_factors: list[dict[str, Any]] = []

        for pid in product_ids:
            monthly_counts = product_monthly.get(pid, {})
            total_orders = sum(monthly_counts.values())

            if total_orders >= 12:
                # Enough data to compute actual seasonal index
                avg_monthly = total_orders / 12.0
                seasonal_index: dict[str, float] = {}
                for month_num in range(1, 13):
                    month_key = f"{month_num:02d}"
                    count = monthly_counts.get(month_key, 0)
                    if avg_monthly > 0:
                        seasonal_index[month_key] = round(count / avg_monthly, 2)
                    else:
                        seasonal_index[month_key] = 1.0

                # Detect peak months (index > 1.15)
                peak_months = [
                    int(m) for m, idx in seasonal_index.items() if idx > 1.15
                ]

                # Seasonality strength: std dev of monthly indices
                vals = list(seasonal_index.values())
                mean_idx = sum(vals) / len(vals)
                variance = sum((v - mean_idx) ** 2 for v in vals) / len(vals)
                strength = round(variance ** 0.5, 3)
            else:
                # Use default retail seasonality
                seasonal_index = dict(_DEFAULT_SEASONAL_INDEX)
                peak_months = [11, 12]
                strength = 0.15

            seasonal_factors.append({
                "product_id": pid,
                "peak_months": peak_months,
                "seasonal_index": seasonal_index,
                "seasonality_strength": strength,
            })

        return {
            "status": "success",
            "seasonal_factors": seasonal_factors,
        }
    except Exception as exc:
        return {
            "status": "error",
            "seasonal_factors": [],
            "error": f"Seasonality detection failed: {exc}",
        }
