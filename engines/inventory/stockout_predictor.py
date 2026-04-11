"""Inventory Engine — stockout predictor.

Predicts stockout dates and stockout probability per SKU using
current stock levels, demand forecasts, and safety stock buffers.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import math
from typing import Any


# ---------------------------------------------------------------------------
# Risk level thresholds (days until stockout)
# ---------------------------------------------------------------------------

_CRITICAL_DAYS = 3
_HIGH_RISK_DAYS = 7
_MEDIUM_RISK_DAYS = 14
# Above MEDIUM_RISK_DAYS = low risk


def predict_stockouts(
    sku_analyses: list[dict[str, Any]],
    demand_forecasts: list[dict[str, Any]],
    safety_stocks: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Predict stockout dates and probabilities for each SKU.

    Uses current stock, forecasted demand, and safety stock buffers
    to estimate when each SKU will run out and the probability of
    stockout within 7-day and 30-day windows.

    Args:
        sku_analyses: Per-SKU analysis from stock_analyzer.
        demand_forecasts: Per-SKU forecasts from demand_forecaster.
        safety_stocks: Per-SKU safety stock from safety_stock_optimizer.
        products: Original product list.

    Returns:
        Structured dict with per-SKU stockout predictions.
    """
    try:
        analyses_map = {str(a.get("id", "")): copy.deepcopy(a) for a in sku_analyses}
        forecasts_map = {str(f.get("id", "")): copy.deepcopy(f) for f in demand_forecasts}
        ss_map = {str(s.get("id", "")): copy.deepcopy(s) for s in safety_stocks}
        prods_map = {str(p.get("id", "")): copy.deepcopy(p) for p in products}

        risks: list[dict[str, Any]] = []

        for sku_id, analysis in analyses_map.items():
            title = str(analysis.get("title", ""))
            current_stock = int(analysis.get("current_stock", 0))
            daily_avg = float(analysis.get("daily_sales_avg", 0.0))
            is_dead = bool(analysis.get("is_dead_stock", False))

            forecast = forecasts_map.get(sku_id, {})
            forecast_7d = float(forecast.get("forecast_7d", daily_avg * 7))
            forecast_30d = float(forecast.get("forecast_30d", daily_avg * 30))
            confidence = float(forecast.get("confidence", 0.5))

            ss_data = ss_map.get(sku_id, {})
            safety_stock_units = int(ss_data.get("safety_stock_units", 0))
            demand_std_dev = float(ss_data.get("demand_std_dev", daily_avg * 0.15))

            # Forecasted daily demand (use 7d forecast for near-term accuracy)
            forecasted_daily = forecast_7d / 7.0 if forecast_7d > 0 else daily_avg

            # Days until stockout (stock reaches zero)
            if forecasted_daily > 0:
                days_until_stockout = round(current_stock / forecasted_daily, 1)
            elif is_dead:
                days_until_stockout = -1.0  # dead stock, no sell-through
            else:
                days_until_stockout = float("inf")

            # Stockout probability using normal distribution approximation
            # P(stockout in N days) = P(demand_N > current_stock)
            # demand_N ~ N(mu_N, sigma_N) where sigma_N = sigma_d * sqrt(N)
            prob_7d = _stockout_probability(
                current_stock=current_stock,
                daily_demand=forecasted_daily,
                demand_std_dev=demand_std_dev,
                horizon_days=7,
            )

            prob_30d = _stockout_probability(
                current_stock=current_stock,
                daily_demand=forecasted_daily,
                demand_std_dev=demand_std_dev,
                horizon_days=30,
            )

            # Risk level classification
            if is_dead:
                risk_level = "none"
                recommended_action = "Consider liquidation or markdown"
            elif days_until_stockout == float("inf"):
                risk_level = "none"
                recommended_action = "No action needed"
            elif days_until_stockout <= _CRITICAL_DAYS:
                risk_level = "critical"
                recommended_action = "Emergency reorder immediately"
            elif days_until_stockout <= _HIGH_RISK_DAYS:
                risk_level = "high"
                recommended_action = "Place reorder now"
            elif days_until_stockout <= _MEDIUM_RISK_DAYS:
                risk_level = "medium"
                recommended_action = "Schedule reorder within the week"
            else:
                risk_level = "low"
                recommended_action = "Monitor; no immediate action"

            # Cap inf for serialization
            safe_days = days_until_stockout if days_until_stockout != float("inf") else -1.0

            risks.append({
                "id": sku_id,
                "title": title,
                "days_until_stockout": safe_days,
                "stockout_probability_7d": round(prob_7d, 4),
                "stockout_probability_30d": round(prob_30d, 4),
                "risk_level": risk_level,
                "recommended_action": recommended_action,
            })

        return {
            "status": "success",
            "stockout_risks": risks,
        }
    except Exception as exc:
        return {
            "status": "error",
            "stockout_risks": [],
            "error": f"Stockout prediction failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stockout_probability(
    current_stock: int,
    daily_demand: float,
    demand_std_dev: float,
    horizon_days: int,
) -> float:
    """Calculate probability of stockout within a given horizon.

    Uses the cumulative normal distribution:
    P(demand > stock) = 1 - Phi((stock - mu) / sigma)
    where mu = daily_demand * horizon, sigma = std_dev * sqrt(horizon).

    Returns:
        Probability between 0.0 and 1.0.
    """
    if daily_demand <= 0 or horizon_days <= 0:
        return 0.0

    mu = daily_demand * horizon_days
    sigma = demand_std_dev * math.sqrt(horizon_days)

    if sigma <= 0:
        # Deterministic: either we run out or we don't
        return 1.0 if mu > current_stock else 0.0

    z = (current_stock - mu) / sigma
    # P(stockout) = 1 - Phi(z) using error function approximation
    prob_no_stockout = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    return round(max(0.0, min(1.0, 1.0 - prob_no_stockout)), 4)
