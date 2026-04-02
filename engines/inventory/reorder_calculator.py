"""Inventory Engine — reorder calculator.

Calculates reorder point (ROP), economic order quantity (EOQ), and
lead time demand for each SKU using real formulas.

EOQ = sqrt(2 * D * S / H)
  where D = annual demand, S = ordering cost, H = holding cost per unit/year

ROP = (daily demand * lead time) + safety stock

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import math
from typing import Any


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_HOLDING_COST_PCT = 0.25   # 25% of unit cost per year
_MIN_ORDER_QTY = 1


def calculate_reorder(
    products: list[dict[str, Any]],
    demand_forecasts: list[dict[str, Any]],
    safety_stocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate ROP, EOQ, and lead-time demand for each SKU.

    Args:
        products: Original product list with unit_cost, reorder_cost, lead_time_days.
        demand_forecasts: Per-SKU demand forecasts from demand_forecaster.
        safety_stocks: Per-SKU safety stock from safety_stock_optimizer.

    Returns:
        Structured dict with per-SKU reorder calculations.
    """
    try:
        prods = {str(p.get("id", "")): copy.deepcopy(p) for p in products}
        forecasts = {str(f.get("id", "")): copy.deepcopy(f) for f in demand_forecasts}
        ss_map = {str(s.get("id", "")): copy.deepcopy(s) for s in safety_stocks}

        calculations: list[dict[str, Any]] = []

        for sku_id, prod in prods.items():
            current_stock = int(prod.get("current_stock", 0))
            unit_cost = float(prod.get("unit_cost", 0.0))
            reorder_cost = float(prod.get("reorder_cost", 0.0))
            lead_time_days = int(prod.get("lead_time_days", 7))

            forecast = forecasts.get(sku_id, {})
            daily_demand = float(forecast.get("current_avg", 0.0))

            ss_data = ss_map.get(sku_id, {})
            safety_stock = int(ss_data.get("safety_stock_units", 0))

            # Annual demand
            annual_demand = daily_demand * 365.0

            # Holding cost per unit per year
            holding_cost = unit_cost * _DEFAULT_HOLDING_COST_PCT

            # --- EOQ: Economic Order Quantity ---
            # EOQ = sqrt(2 * D * S / H)
            if annual_demand > 0 and holding_cost > 0 and reorder_cost > 0:
                eoq = math.sqrt(
                    (2.0 * annual_demand * reorder_cost) / holding_cost
                )
                eoq = max(int(round(eoq)), _MIN_ORDER_QTY)
            else:
                # Fallback: order 30 days of supply
                eoq = max(int(round(daily_demand * 30)), _MIN_ORDER_QTY)

            # --- Lead Time Demand ---
            lead_time_demand = daily_demand * lead_time_days

            # --- ROP: Reorder Point ---
            # ROP = lead_time_demand + safety_stock
            reorder_point = int(math.ceil(lead_time_demand + safety_stock))

            # --- Should we reorder now? ---
            needs_reorder = current_stock <= reorder_point

            # Units remaining before hitting reorder point
            units_until_reorder = max(current_stock - reorder_point, 0)

            # Estimated cost of placing one order
            order_units_cost = eoq * unit_cost
            estimated_reorder_cost = round(order_units_cost + reorder_cost, 2)

            calculations.append({
                "id": sku_id,
                "reorder_point": reorder_point,
                "economic_order_qty": eoq,
                "lead_time_demand": round(lead_time_demand, 1),
                "needs_reorder": needs_reorder,
                "units_until_reorder": units_until_reorder,
                "estimated_reorder_cost": estimated_reorder_cost,
            })

        return {
            "status": "success",
            "calculations": calculations,
        }
    except Exception as exc:
        return {
            "status": "error",
            "calculations": [],
            "error": f"Reorder calculation failed: {exc}",
        }
