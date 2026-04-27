"""Shipping Optimization Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Order/Product Data → Rate Calculator → Carrier Comparator →
  Threshold Optimizer → Delivery Estimator → Cost Allocator →
  Zone Mapper → Strategy Recommender → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, origin_zip, avg_order_value,
           monthly_orders, current_shipping_strategy}, meta, error}
  Output: {status, data: {recommended_strategy, carrier_comparison,
           free_shipping_threshold, estimated_savings_monthly,
           delivery_times, confidence}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .rate_calculator import calculate_rates
from .carrier_comparator import compare_carriers
from .threshold_optimizer import optimize_threshold
from .delivery_estimator import estimate_delivery
from .cost_allocator import allocate_costs
from .zone_mapper import map_zones
from .strategy_recommender import recommend_strategy
from .memory_reader import read_past_shipping, compute_input_hash
from .memory_writer import write_shipping_result
from engines._shopify_hydrator import hydrate


class ShippingOptimizationEngine:
    """Shipping Optimization Engine — orchestrator only, no logic."""

    ENGINE_NAME = "shipping_optimization"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full shipping optimization pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ShippingOptimizationOutput dict.
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
            return self._fail("At least one product is required", 0.0)

        origin_zip = str(data.get("origin_zip", "10001"))
        avg_order_value = float(data.get("avg_order_value", 45.0))
        monthly_orders = int(data.get("monthly_orders", 500))
        current_strategy = str(data.get("current_shipping_strategy", "flat_rate_5.99"))

        # ---- Stage 1: Read past shipping decisions (non-blocking) ----
        _past = read_past_shipping(limit=5)
        _input_hash = compute_input_hash(data)

        # ---- Stage 2: Zone Mapper ----
        zone_result = map_zones(origin_zip=origin_zip)
        if zone_result.get("status") == "error":
            return self._fail(
                f"Zone mapping failed: {zone_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        weighted_zone = int(round(zone_result.get("weighted_avg_zone", 5)))
        weighted_zone = max(1, min(8, weighted_zone))

        # ---- Stage 3: Rate Calculator ----
        rates_result = calculate_rates(
            products=products,
            zone=weighted_zone,
        )
        if rates_result.get("status") == "error":
            return self._fail(
                f"Rate calculation failed: {rates_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 4: Carrier Comparator ----
        carrier_result = compare_carriers(
            rates=rates_result.get("rates", []),
            zone=weighted_zone,
            priority="value",
        )
        if carrier_result.get("status") == "error":
            return self._fail(
                f"Carrier comparison failed: {carrier_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 5: Threshold Optimizer ----
        cheapest = rates_result.get("cheapest", {})
        avg_shipping_cost = float(cheapest.get("total", 8.50)) if cheapest else 8.50

        threshold_result_raw = optimize_threshold(
            avg_order_value=avg_order_value,
            monthly_orders=monthly_orders,
            avg_shipping_cost=avg_shipping_cost,
            avg_margin_pct=0.40,
            current_strategy=current_strategy,
        )
        if threshold_result_raw.get("status") == "error":
            return self._fail(
                f"Threshold optimization failed: {threshold_result_raw.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        threshold_data = threshold_result_raw.get("threshold", {})

        # ---- Stage 6: Delivery Estimator ----
        delivery_result = estimate_delivery(zone=weighted_zone)
        if delivery_result.get("status") == "error":
            return self._fail(
                f"Delivery estimation failed: {delivery_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 7: Cost Allocator ----
        allocation_result = allocate_costs(
            avg_shipping_cost=avg_shipping_cost,
            avg_order_value=avg_order_value,
            avg_margin_pct=0.40,
            monthly_orders=monthly_orders,
        )
        if allocation_result.get("status") == "error":
            return self._fail(
                f"Cost allocation failed: {allocation_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 8: Strategy Recommender ----
        strategy_result = recommend_strategy(
            rates_result=rates_result,
            carrier_result=carrier_result,
            threshold_result=threshold_data,
            delivery_result=delivery_result,
            allocation_result=allocation_result,
            zone_result=zone_result,
            avg_order_value=avg_order_value,
            monthly_orders=monthly_orders,
            current_strategy=current_strategy,
        )
        if strategy_result.get("status") == "error":
            return self._fail(
                f"Strategy recommendation failed: {strategy_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        recommendation = strategy_result.get("recommendation", {})
        estimated_savings = float(strategy_result.get("estimated_savings_monthly", 0.0))

        # ---- Stage 9: Memory Writer (non-fatal) ----
        _write = write_shipping_result(
            recommended_strategy=recommendation,
            free_shipping_threshold=float(threshold_data.get("recommended_threshold", 0.0)),
            estimated_savings_monthly=estimated_savings,
            carrier_comparison_count=carrier_result.get("count", 0),
            confidence=float(recommendation.get("confidence", 0.0)),
            input_hash=_input_hash,
        )

        # ---- Stage 10: Assemble output ----
        elapsed = time.monotonic() - start

        # Build delivery times summary
        delivery_estimates = delivery_result.get("estimates", [])
        delivery_summary = delivery_result.get("summary", {})

        # Top 5 carrier comparisons for output
        comparisons = carrier_result.get("comparisons", [])[:5]

        return {
            "status": "success",
            "data": {
                "recommended_strategy": recommendation,
                "carrier_comparison": comparisons,
                "free_shipping_threshold": float(threshold_data.get("recommended_threshold", 0.0)),
                "estimated_savings_monthly": round(estimated_savings, 2),
                "delivery_times": {
                    "summary": delivery_summary,
                    "by_carrier": delivery_estimates[:6],
                    "zone": weighted_zone,
                },
                "zone_distribution": zone_result.get("distribution", []),
                "cost_allocations": allocation_result.get("allocations", []),
                "confidence": float(recommendation.get("confidence", 0.0)),
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
