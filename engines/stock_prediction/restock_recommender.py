"""Stock Prediction Engine — restock recommender.

Recommends when and how much to restock each product based on demand
models, seasonal factors, and lead times.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import time
from typing import Any


def recommend_restocks(
    products: list[dict[str, Any]],
    demand_models: list[dict[str, Any]],
    seasonal_factors: list[dict[str, Any]],
    lead_times: list[dict[str, Any]],
    current_stock: dict[str, int],
) -> dict[str, Any]:
    """Recommend restocking schedule and quantities per product.

    Args:
        products: List of ProductStock dicts.
        demand_models: List of DemandModel dicts from demand_modeler.
        seasonal_factors: List of SeasonalFactor dicts from seasonality_detector.
        lead_times: List of LeadTimeEstimate dicts from lead_time_estimator.
        current_stock: Dict mapping product_id to current stock quantity.

    Returns:
        Structured dict with per-product restock recommendations.
    """
    try:
        products = copy.deepcopy(products)

        # Build lookups
        demand_map = {str(m.get("product_id", "")): m for m in demand_models}
        season_map = {str(s.get("product_id", "")): s for s in seasonal_factors}
        lt_map = {str(lt.get("product_id", "")): lt for lt in lead_times}

        # Current month for seasonal adjustment
        current_month = int(time.strftime("%m"))
        month_key = f"{current_month:02d}"

        recommendations: list[dict[str, Any]] = []

        for product in products:
            pid = str(product.get("id", "unknown"))
            stock = int(current_stock.get(pid, product.get("current_stock", 0)))

            demand = demand_map.get(pid, {})
            daily_demand = float(demand.get("avg_daily_demand", 0.0))

            season = season_map.get(pid, {})
            seasonal_index = season.get("seasonal_index", {})
            season_mult = float(seasonal_index.get(month_key, 1.0))

            lt = lt_map.get(pid, {})
            lead_time_days = int(lt.get("avg_lead_time_days", 14))
            lt_std = float(lt.get("lead_time_std_dev", 2.0))

            # Adjusted daily demand with seasonality
            adjusted_demand = daily_demand * season_mult

            # 30-day and 90-day demand predictions
            predicted_30d = round(adjusted_demand * 30.0, 1)
            predicted_90d = round(adjusted_demand * 90.0, 1)

            # Safety stock: 1.65 * std_dev * sqrt(lead_time) (95% service)
            volatility = float(demand.get("demand_volatility", 0.3))
            demand_std = daily_demand * volatility
            safety_stock = round(
                1.65 * demand_std * (lead_time_days ** 0.5) +
                1.65 * adjusted_demand * (lt_std / max(lead_time_days, 1))
            )

            # Reorder point
            lead_time_demand = adjusted_demand * lead_time_days
            reorder_point = round(lead_time_demand + safety_stock)

            # Days until restock needed
            if adjusted_demand > 0:
                days_until_reorder = max(
                    round((stock - reorder_point) / adjusted_demand), 0
                )
            else:
                days_until_reorder = 999

            # Restock date
            restock_timestamp = time.time() + (days_until_reorder * 86400)
            restock_date = time.strftime(
                "%Y-%m-%d", time.gmtime(restock_timestamp)
            )

            # Restock quantity: cover 30 days of demand + safety stock - current
            restock_qty = max(
                round(predicted_30d + safety_stock - stock), 0
            )

            # Urgency classification
            if days_until_reorder <= 0:
                urgency = "critical"
            elif days_until_reorder <= 7:
                urgency = "high"
            elif days_until_reorder <= 14:
                urgency = "medium"
            else:
                urgency = "low"

            recommendations.append({
                "product_id": pid,
                "predicted_demand_30d": predicted_30d,
                "predicted_demand_90d": predicted_90d,
                "restock_date": restock_date,
                "restock_qty": restock_qty,
                "urgency": urgency,
            })

        return {
            "status": "success",
            "recommendations": recommendations,
        }
    except Exception as exc:
        return {
            "status": "error",
            "recommendations": [],
            "error": f"Restock recommendation failed: {exc}",
        }
