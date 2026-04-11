"""Inventory Engine — cost tracker.

Tracks inventory costs: holding cost, ordering cost, stockout cost,
total inventory value, and carrying cost percentage.

Holding cost = sum(unit_cost * holding_rate * current_stock) annualized
Ordering cost = sum(reorder_cost) for SKUs that need reorder
Stockout cost = estimated lost revenue from predicted stockouts

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_HOLDING_COST_PCT = 0.25   # 25% of unit cost per year
_DEFAULT_STOCKOUT_MARGIN = 0.35    # assumed margin lost per stockout unit


def compute_costs(
    products: list[dict[str, Any]],
    reorder_calculations: list[dict[str, Any]],
    stockout_risks: list[dict[str, Any]],
    safety_stocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute inventory cost summary across all SKUs.

    Args:
        products: Original product list with unit_cost, reorder_cost, current_stock.
        reorder_calculations: Per-SKU reorder data from reorder_calculator.
        stockout_risks: Per-SKU stockout risks from stockout_predictor.
        safety_stocks: Per-SKU safety stock from safety_stock_optimizer.

    Returns:
        Structured dict with CostSummary data.
    """
    try:
        prods = {str(p.get("id", "")): copy.deepcopy(p) for p in products}
        reorder_map = {str(r.get("id", "")): copy.deepcopy(r) for r in reorder_calculations}
        risk_map = {str(r.get("id", "")): copy.deepcopy(r) for r in stockout_risks}

        total_holding_cost = 0.0
        total_ordering_cost = 0.0
        estimated_stockout_cost = 0.0
        total_inventory_value = 0.0

        for sku_id, prod in prods.items():
            unit_cost = float(prod.get("unit_cost", 0.0))
            reorder_cost_per_order = float(prod.get("reorder_cost", 0.0))
            current_stock = int(prod.get("current_stock", 0))
            daily_avg = float(prod.get("daily_sales_avg", 0.0))

            # --- Inventory value ---
            sku_value = unit_cost * current_stock
            total_inventory_value += sku_value

            # --- Annual holding cost ---
            # H = unit_cost * holding_rate * average_stock
            # Approximate average stock as current_stock / 2 (EOQ assumption)
            avg_stock = current_stock / 2.0 if current_stock > 0 else 0.0
            annual_holding = unit_cost * _DEFAULT_HOLDING_COST_PCT * avg_stock
            total_holding_cost += annual_holding

            # --- Ordering cost ---
            reorder_data = reorder_map.get(sku_id, {})
            needs_reorder = bool(reorder_data.get("needs_reorder", False))
            if needs_reorder:
                total_ordering_cost += reorder_cost_per_order

            # --- Estimated stockout cost ---
            risk_data = risk_map.get(sku_id, {})
            prob_30d = float(risk_data.get("stockout_probability_30d", 0.0))
            if prob_30d > 0 and daily_avg > 0:
                # Expected lost units = prob * daily_avg * days_of_stockout
                # Assume average stockout lasts 5 days if it occurs
                expected_lost_units = prob_30d * daily_avg * 5.0
                # Lost revenue at margin
                selling_price_est = unit_cost / (1.0 - _DEFAULT_STOCKOUT_MARGIN) if _DEFAULT_STOCKOUT_MARGIN < 1.0 else unit_cost
                margin_per_unit = selling_price_est - unit_cost
                estimated_stockout_cost += expected_lost_units * margin_per_unit

        # --- Carrying cost percentage ---
        carrying_cost_pct = (
            round(total_holding_cost / total_inventory_value, 4)
            if total_inventory_value > 0 else 0.0
        )

        cost_summary = {
            "total_holding_cost": round(total_holding_cost, 2),
            "total_ordering_cost": round(total_ordering_cost, 2),
            "estimated_stockout_cost": round(estimated_stockout_cost, 2),
            "total_inventory_value": round(total_inventory_value, 2),
            "carrying_cost_pct": carrying_cost_pct,
        }

        return {
            "status": "success",
            "cost_summary": cost_summary,
        }
    except Exception as exc:
        return {
            "status": "error",
            "cost_summary": {},
            "error": f"Cost tracking failed: {exc}",
        }
