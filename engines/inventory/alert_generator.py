"""Inventory Engine — alert generator.

Generates actionable alerts based on stock analysis, reorder status,
stockout risk, and demand trends.

Alert types: low_stock, overstock, slow_moving, reorder_needed,
             dead_stock, stockout_imminent.
Severity levels: critical, high, medium, low, info.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def generate_alerts(
    sku_analyses: list[dict[str, Any]],
    reorder_calculations: list[dict[str, Any]],
    stockout_risks: list[dict[str, Any]],
    demand_forecasts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate inventory alerts across all SKUs.

    Scans every SKU for actionable conditions and produces prioritized
    alerts sorted by severity.

    Args:
        sku_analyses: Per-SKU analysis from stock_analyzer.
        reorder_calculations: Per-SKU reorder data from reorder_calculator.
        stockout_risks: Per-SKU stockout risks from stockout_predictor.
        demand_forecasts: Per-SKU forecasts from demand_forecaster.

    Returns:
        Structured dict with list of InventoryAlert dicts.
    """
    try:
        analyses_map = {str(a.get("id", "")): copy.deepcopy(a) for a in sku_analyses}
        reorder_map = {str(r.get("id", "")): copy.deepcopy(r) for r in reorder_calculations}
        risk_map = {str(r.get("id", "")): copy.deepcopy(r) for r in stockout_risks}
        forecast_map = {str(f.get("id", "")): copy.deepcopy(f) for f in demand_forecasts}

        alerts: list[dict[str, Any]] = []

        for sku_id, analysis in analyses_map.items():
            title = str(analysis.get("title", ""))
            stock_status = str(analysis.get("stock_status", ""))
            current_stock = int(analysis.get("current_stock", 0))
            is_dead = bool(analysis.get("is_dead_stock", False))
            days_of_stock = analysis.get("days_of_stock", -1)
            turnover_rate = float(analysis.get("turnover_rate", 0.0))

            risk_data = risk_map.get(sku_id, {})
            risk_level = str(risk_data.get("risk_level", ""))
            days_until_stockout = risk_data.get("days_until_stockout", -1)

            reorder_data = reorder_map.get(sku_id, {})
            needs_reorder = bool(reorder_data.get("needs_reorder", False))
            eoq = int(reorder_data.get("economic_order_qty", 0))

            forecast = forecast_map.get(sku_id, {})
            trend = str(forecast.get("trend", ""))

            # --- Dead stock alert ---
            if is_dead:
                alerts.append({
                    "alert_type": "dead_stock",
                    "severity": "medium",
                    "sku_id": sku_id,
                    "title": title,
                    "message": (
                        f"{title} ({sku_id}) has {current_stock} units "
                        f"with near-zero sales velocity. Considered dead stock."
                    ),
                    "recommended_action": (
                        "Consider liquidation, bundling, or markdown strategy "
                        "to recover capital."
                    ),
                })

            # --- Stockout imminent alert ---
            if risk_level == "critical" and not is_dead:
                alerts.append({
                    "alert_type": "stockout_imminent",
                    "severity": "critical",
                    "sku_id": sku_id,
                    "title": title,
                    "message": (
                        f"{title} ({sku_id}) will stock out in "
                        f"~{days_until_stockout} days at current demand."
                    ),
                    "recommended_action": (
                        f"Emergency reorder of {eoq} units immediately. "
                        f"Consider expedited shipping."
                    ),
                })

            # --- Low stock alert ---
            if stock_status in ("low", "critical") and risk_level != "critical":
                severity = "high" if stock_status == "critical" else "medium"
                alerts.append({
                    "alert_type": "low_stock",
                    "severity": severity,
                    "sku_id": sku_id,
                    "title": title,
                    "message": (
                        f"{title} ({sku_id}) has {current_stock} units remaining "
                        f"(~{days_of_stock} days of stock)."
                    ),
                    "recommended_action": (
                        f"Reorder {eoq} units. Current stock is {stock_status}."
                    ),
                })

            # --- Reorder needed alert ---
            if needs_reorder and stock_status not in ("critical",) and risk_level != "critical":
                alerts.append({
                    "alert_type": "reorder_needed",
                    "severity": "medium",
                    "sku_id": sku_id,
                    "title": title,
                    "message": (
                        f"{title} ({sku_id}) has reached its reorder point. "
                        f"Current stock: {current_stock}."
                    ),
                    "recommended_action": (
                        f"Place order for {eoq} units (EOQ). "
                        f"Estimated cost in reorder plan."
                    ),
                })

            # --- Overstock alert ---
            if stock_status == "overstocked":
                alerts.append({
                    "alert_type": "overstock",
                    "severity": "low",
                    "sku_id": sku_id,
                    "title": title,
                    "message": (
                        f"{title} ({sku_id}) has {current_stock} units — "
                        f"~{days_of_stock} days of stock. Overstocked."
                    ),
                    "recommended_action": (
                        "Reduce future order quantities. Consider promotions "
                        "or channel diversification to increase velocity."
                    ),
                })

            # --- Slow-moving alert ---
            if (
                turnover_rate < 3.0
                and not is_dead
                and current_stock > 0
                and trend in ("decline", "strong_decline")
            ):
                alerts.append({
                    "alert_type": "slow_moving",
                    "severity": "low",
                    "sku_id": sku_id,
                    "title": title,
                    "message": (
                        f"{title} ({sku_id}) has a turnover rate of "
                        f"{turnover_rate} with declining demand."
                    ),
                    "recommended_action": (
                        "Review pricing strategy. Consider markdown, "
                        "bundling, or discontinuation."
                    ),
                })

        # Sort alerts by severity: critical > high > medium > low > info
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        alerts.sort(key=lambda a: severity_order.get(a.get("severity", "info"), 5))

        return {
            "status": "success",
            "alerts": alerts,
            "total_alerts": len(alerts),
        }
    except Exception as exc:
        return {
            "status": "error",
            "alerts": [],
            "error": f"Alert generation failed: {exc}",
        }
