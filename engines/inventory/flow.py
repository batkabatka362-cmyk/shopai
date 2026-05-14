"""Inventory Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Stock Data → Stock Analyzer → Demand Forecaster → Safety Stock Optimizer →
  Reorder Calculator → Stockout Predictor → Allocation Planner →
  Alert Generator → Cost Tracker → Memory Writer → Output

Note: Safety stock runs before reorder because ROP = lead_time_demand + safety_stock.

Engine contract:
  Input:  {status, data: {products, warehouse_capacity, service_level_target}, meta, error}
  Output: {status, data: {inventory_health, reorder_plan, stockout_risks, alerts, cost_summary}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .stock_analyzer import analyze_stock
from .demand_forecaster import forecast_demand
from .safety_stock_optimizer import optimize_safety_stock
from .reorder_calculator import calculate_reorder
from .stockout_predictor import predict_stockouts
from .allocation_planner import plan_allocation
from .alert_generator import generate_alerts
from .cost_tracker import compute_costs
from .inventory_applier import (
    apply_inventory_tags,
    enqueue_inventory_tags_for_approval,
)
from .memory_reader import read_past_inventory
from .memory_writer import write_inventory_result
from engines._shopify_hydrator import hydrate


class InventoryEngine:
    """Inventory Engine — orchestrator only, no logic."""

    ENGINE_NAME = "inventory"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full inventory pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            InventoryOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation (no mutation) ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        products = data.get("products", [])
        warehouse_capacity = int(data.get("warehouse_capacity", 10000))
        service_level_target = float(data.get("service_level_target", 0.95))

        # Auto-hydrate products from Shopify when caller left the
        # list empty. Pre-existing failure semantics preserved:
        # empty supplied AND empty hydrated → standard error.
        products = hydrate(
            supplied=products if isinstance(products, list) else [],
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not products:
            return self._fail("Product list is required", 0.0)

        # ---- Stage 1: Read past inventory (non-blocking) ----
        _past = read_past_inventory(limit=5)

        # ---- Stage 2: Stock Analyzer ----
        stock_result = analyze_stock(
            products=products,
            warehouse_capacity=warehouse_capacity,
        )
        if stock_result.get("status") == "error":
            return self._fail(
                f"Stock analysis failed: {stock_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        stock_analysis = stock_result.get("analysis", {})
        sku_analyses = stock_analysis.get("sku_analyses", [])

        # ---- Stage 3: Demand Forecaster (Mistral) ----
        demand_result = forecast_demand(
            sku_analyses=sku_analyses,
        )
        if demand_result.get("status") == "error":
            return self._fail(
                f"Demand forecasting failed: {demand_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        demand_forecasts = demand_result.get("forecasts", [])

        # ---- Stage 4: Safety Stock Optimizer (Mistral) ----
        safety_result = optimize_safety_stock(
            sku_analyses=sku_analyses,
            demand_forecasts=demand_forecasts,
            products=products,
            service_level_target=service_level_target,
        )
        if safety_result.get("status") == "error":
            return self._fail(
                f"Safety stock optimization failed: {safety_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        safety_stocks = safety_result.get("safety_stocks", [])

        # ---- Stage 5: Reorder Calculator ----
        reorder_result = calculate_reorder(
            products=products,
            demand_forecasts=demand_forecasts,
            safety_stocks=safety_stocks,
        )
        if reorder_result.get("status") == "error":
            return self._fail(
                f"Reorder calculation failed: {reorder_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        reorder_calculations = reorder_result.get("calculations", [])

        # ---- Stage 6: Stockout Predictor ----
        stockout_result = predict_stockouts(
            sku_analyses=sku_analyses,
            demand_forecasts=demand_forecasts,
            safety_stocks=safety_stocks,
            products=products,
        )
        if stockout_result.get("status") == "error":
            return self._fail(
                f"Stockout prediction failed: {stockout_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        stockout_risks = stockout_result.get("stockout_risks", [])

        # ---- Stage 7: Allocation Planner (Qwen) ----
        allocation_result = plan_allocation(
            sku_analyses=sku_analyses,
            demand_forecasts=demand_forecasts,
            reorder_calculations=reorder_calculations,
            stockout_risks=stockout_risks,
            warehouse_capacity=warehouse_capacity,
        )
        if allocation_result.get("status") == "error":
            return self._fail(
                f"Allocation planning failed: {allocation_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        allocations = allocation_result.get("allocations", [])

        # ---- Stage 8: Alert Generator ----
        alert_result = generate_alerts(
            sku_analyses=sku_analyses,
            reorder_calculations=reorder_calculations,
            stockout_risks=stockout_risks,
            demand_forecasts=demand_forecasts,
        )
        if alert_result.get("status") == "error":
            return self._fail(
                f"Alert generation failed: {alert_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        alerts = alert_result.get("alerts", [])

        # ---- Stage 9: Cost Tracker ----
        cost_result = compute_costs(
            products=products,
            reorder_calculations=reorder_calculations,
            stockout_risks=stockout_risks,
            safety_stocks=safety_stocks,
        )
        if cost_result.get("status") == "error":
            return self._fail(
                f"Cost tracking failed: {cost_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        cost_summary = cost_result.get("cost_summary", {})

        # ---- Stage 10: Memory Writer (non-fatal) ----
        # Build reorder plan for output
        ss_map = {str(s.get("id", "")): s for s in safety_stocks}
        prod_map = {str(p.get("id", "")): p for p in products}
        reorder_plan: list[dict[str, Any]] = []
        for calc in reorder_calculations:
            sku_id = str(calc.get("id", ""))
            prod = prod_map.get(sku_id, {})
            ss = ss_map.get(sku_id, {})
            reorder_plan.append({
                "id": sku_id,
                "title": str(prod.get("title", "")),
                "reorder_point": calc.get("reorder_point", 0),
                "economic_order_qty": calc.get("economic_order_qty", 0),
                "safety_stock": int(ss.get("safety_stock_units", 0)),
                "needs_reorder": calc.get("needs_reorder", False),
                "estimated_cost": calc.get("estimated_reorder_cost", 0.0),
            })

        _write_result = write_inventory_result(
            inventory_health=stock_analysis,
            reorder_plan=reorder_plan,
            stockout_risks=stockout_risks,
            alerts=alerts,
            cost_summary=cost_summary,
        )

        # ---- Stage 10.5: Inventory state-tag writeback (opt-in) ----
        # Default OFF so existing callers stay in pure-recommendation
        # mode. Two opt-in modes:
        #
        #   data.apply_inventory_tags=True + data.require_approval=False
        #     → SHOPIFY_UPDATE_PRODUCT.tags immediately per flagged SKU
        #   data.apply_inventory_tags=True + data.require_approval=True
        #     → enqueue each tag-update proposal to core.approval;
        #       merchant approves via /api/pending-actions before
        #       the mutation lands
        #
        # Both paths share the same upstream filters (stockout risk
        # imminent / needs_reorder flag / classification dead /
        # overstocked) and the same tag merge dedup. A SKU that
        # already carries every relevant state tag short-circuits
        # with ``no_new_tags`` either way.
        tag_apply_results: list[dict[str, Any]] = []
        sku_analyses_for_tags = stock_analysis.get(
            "sku_analyses", sku_analyses,
        )
        if data.get("apply_inventory_tags") is True:
            if data.get("require_approval") is True:
                tag_apply_results = enqueue_inventory_tags_for_approval(
                    products=products,
                    stockout_risks=stockout_risks,
                    reorder_calculations=reorder_calculations,
                    stock_analyses=sku_analyses_for_tags,
                )
            else:
                tag_apply_results = apply_inventory_tags(
                    products=products,
                    stockout_risks=stockout_risks,
                    reorder_calculations=reorder_calculations,
                    stock_analyses=sku_analyses_for_tags,
                )

        # ---- Stage 11: Assemble output ----
        elapsed = time.monotonic() - start

        inventory_health: dict[str, Any] = {
            "total_skus": stock_analysis.get("total_skus", 0),
            "healthy_count": stock_analysis.get("healthy_count", 0),
            "low_count": stock_analysis.get("low_count", 0),
            "critical_count": stock_analysis.get("critical_count", 0),
            "overstocked_count": stock_analysis.get("overstocked_count", 0),
            "dead_stock_count": stock_analysis.get("dead_stock_count", 0),
            "avg_turnover_rate": stock_analysis.get("avg_turnover_rate", 0.0),
            "warehouse_utilization": stock_analysis.get("warehouse_utilization", 0.0),
        }

        return {
            "status": "success",
            "data": {
                "inventory_health": inventory_health,
                "reorder_plan": reorder_plan,
                "stockout_risks": stockout_risks,
                "alerts": alerts,
                "cost_summary": cost_summary,
                # Stage 10.5 output. Empty list when the opt-in
                # flag is off; one entry per flagged SKU otherwise
                # (carries pending_action_id when the approval-
                # queue branch fired).
                "tag_apply_results": tag_apply_results,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
