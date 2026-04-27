"""Dynamic Pricing Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Market Signals -> Signal Collector -> Demand Analyzer -> Competition Monitor ->
  Inventory Assessor -> Time Factor Analyzer -> Price Adjuster ->
  Impact Estimator -> Change Validator -> Memory Writer -> Output

Engine contract:
  Input:  {status, data: {products: [{id, current_price, cogs, daily_sales}],
           market_signals: {demand_index, competitor_prices, inventory_days, season}},
           meta, error}
  Output: {status, data: {adjustments: [{product_id, current_price, new_price,
           change_pct, reason}], summary: {total_adjustments, avg_change_pct,
           estimated_revenue_impact}}, meta: {engine: "dynamic_pricing"}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .signal_collector import collect_signals
from .demand_analyzer import analyze_demand
from .competition_monitor import monitor_competition
from .inventory_assessor import assess_inventory
from .time_factor_analyzer import analyze_time_factors
from .price_adjuster import adjust_price
from .impact_estimator import estimate_impact
from .change_validator import validate_change
from .memory_reader import read_recent_changes
from .memory_writer import write_pricing_change
from engines._shopify_hydrator import hydrate


class DynamicPricingEngine:
    """Dynamic Pricing Engine — orchestrator only, no logic."""

    ENGINE_NAME = "dynamic_pricing"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full dynamic pricing pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            DynamicPricingOutput dict.
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
        if not isinstance(products, list):
            products = []
        # Auto-hydrate products from Shopify when caller left the
        # list empty. Pre-existing failure semantics preserved:
        # empty supplied AND empty hydrated → standard error.
        products = hydrate(
            supplied=products,
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )
        if not products:
            return self._fail("At least one product is required", 0.0)

        market_signals = data.get("market_signals", {})
        if not isinstance(market_signals, dict):
            return self._fail("'market_signals' must be a dict", 0.0)

        # ---- Process each product through the pipeline ----
        adjustments: list[dict[str, Any]] = []
        total_revenue_impact = 0.0

        for product in products:
            result = self._process_single_product(product, market_signals)
            if result is not None:
                adjustments.append(result["output"])
                total_revenue_impact += result.get("revenue_impact", 0.0)

        # ---- Build summary ----
        total_adjustments = len(adjustments)
        change_pcts = [a["change_pct"] for a in adjustments]
        avg_change_pct = (
            round(sum(change_pcts) / len(change_pcts), 2)
            if change_pcts else 0.0
        )

        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "adjustments": adjustments,
                "summary": {
                    "total_adjustments": total_adjustments,
                    "avg_change_pct": avg_change_pct,
                    "estimated_revenue_impact": round(total_revenue_impact, 2),
                },
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Per-product pipeline
    # -------------------------------------------------------------------

    def _process_single_product(
        self,
        product: dict[str, Any],
        market_signals: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Run the full pipeline for a single product.

        Returns dict with 'output' (AdjustmentOutput) and 'revenue_impact',
        or None if the product fails early and should be skipped.
        """
        product_id = str(product.get("id", "unknown"))

        # ---- Stage 1: Signal Collector ----
        collected = collect_signals(product=product, market_signals=market_signals)
        if collected.get("status") == "error":
            return None
        signals = collected.get("signals", {})

        # ---- Stage 2: Demand Analyzer (Mistral) ----
        demand_result = analyze_demand(signals=signals)
        if demand_result.get("status") == "error":
            return None
        demand_analysis = demand_result.get("analysis", {})

        # ---- Stage 3: Competition Monitor ----
        comp_result = monitor_competition(signals=signals)
        if comp_result.get("status") == "error":
            return None
        competition_snapshot = comp_result.get("snapshot", {})

        # ---- Stage 4: Inventory Assessor ----
        inv_result = assess_inventory(signals=signals)
        if inv_result.get("status") == "error":
            return None
        inventory_assessment = inv_result.get("assessment", {})

        # ---- Stage 5: Time Factor Analyzer (LLaMA) ----
        time_result = analyze_time_factors(signals=signals)
        if time_result.get("status") == "error":
            return None
        time_factors = time_result.get("factors", {})

        # ---- Stage 6: Price Adjuster (Qwen) ----
        adj_result = adjust_price(
            signals=signals,
            demand_analysis=demand_analysis,
            competition_snapshot=competition_snapshot,
            inventory_assessment=inventory_assessment,
            time_factors=time_factors,
        )
        if adj_result.get("status") == "error":
            return None
        adjustment = adj_result.get("adjustment", {})

        # ---- Stage 7: Impact Estimator ----
        impact_result = estimate_impact(
            adjustment=adjustment,
            signals=signals,
        )
        if impact_result.get("status") == "error":
            return None
        impact = impact_result.get("estimate", {})

        # ---- Stage 8: Change Validator (Mistral) ----
        # Fetch recent changes for 24h window enforcement
        recent_result = read_recent_changes(product_id=product_id, hours=24.0)
        recent_changes = recent_result.get("records", [])

        val_result = validate_change(
            adjustment=adjustment,
            impact_estimate=impact,
            signals=signals,
            recent_changes=recent_changes,
        )
        if val_result.get("status") == "error":
            return None
        validation = val_result.get("validation", {})

        # If not approved, use current price (no change)
        approved = validation.get("approved", False)
        if approved:
            new_price = float(adjustment.get("new_price", 0.0))
            change_pct = float(adjustment.get("change_pct", 0.0))
            reason = str(impact.get("reason", ""))
        else:
            new_price = float(adjustment.get("current_price", 0.0))
            change_pct = 0.0
            reason = f"Blocked: {validation.get('rejection_reason', 'validation failed')}"

        current_price = float(adjustment.get("current_price", 0.0))
        revenue_change = float(impact.get("estimated_revenue_change", 0.0)) if approved else 0.0

        # ---- Stage 9: Memory Writer (non-fatal) ----
        _write = write_pricing_change(
            product_id=product_id,
            current_price=current_price,
            new_price=new_price,
            change_pct=change_pct,
            reason=reason,
            approved=approved,
            estimated_revenue_change=revenue_change,
        )

        # ---- Build output ----
        return {
            "output": {
                "product_id": product_id,
                "current_price": round(current_price, 2),
                "new_price": round(new_price, 2),
                "change_pct": round(change_pct, 2),
                "reason": reason,
            },
            "revenue_impact": revenue_change,
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
