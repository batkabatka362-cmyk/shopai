"""Price Elasticity Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Sensitivity Calculator → Demand Curve Builder →
  Optimal Price Finder → Segment Analyzer → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, price_history, sales_data}, meta, error}
  Output: {status, data: {elasticity: [{product_id, coefficient, optimal_price}]}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .sensitivity_calculator import calculate_sensitivity
from .demand_curve_builder import build_demand_curves
from .optimal_price_finder import find_optimal_prices
from .segment_analyzer import analyze_segments
from .memory_reader import read_past_elasticities
from .memory_writer import write_elasticity_result
from engines._shopify_hydrator import hydrate


class PriceElasticityEngine:
    """Price Elasticity Engine — orchestrator only, no logic."""

    ENGINE_NAME = "price_elasticity"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full elasticity pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ElasticityOutput dict.
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
        price_history = data.get("price_history", [])
        sales_data = data.get("sales_data", [])

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

        # ---- Stage 1: Read past elasticities (non-blocking) ----
        _past = read_past_elasticities(limit=5)

        # ---- Stage 2: Sensitivity Calculator ----
        sens_result = calculate_sensitivity(
            products=products,
            price_history=price_history,
        )
        if sens_result.get("status") == "error":
            return self._fail(
                f"Sensitivity calculation failed: {sens_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        sensitivities = sens_result.get("sensitivities", [])

        # ---- Stage 3: Demand Curve Builder ----
        curve_result = build_demand_curves(
            products=products,
            price_history=price_history,
            sensitivities=sensitivities,
        )
        if curve_result.get("status") == "error":
            return self._fail(
                f"Demand curve building failed: {curve_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        curves = curve_result.get("curves", [])

        # ---- Stage 4: Optimal Price Finder ----
        price_result = find_optimal_prices(
            products=products,
            curves=curves,
        )
        if price_result.get("status") == "error":
            return self._fail(
                f"Optimal price finding failed: {price_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        optimal_prices = price_result.get("optimal_prices", [])

        # ---- Stage 5: Segment Analyzer ----
        segment_result = analyze_segments(
            products=products,
            sensitivities=sensitivities,
        )
        if segment_result.get("status") == "error":
            return self._fail(
                f"Segment analysis failed: {segment_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        segments = segment_result.get("segments", [])

        # ---- Stage 6: Assemble elasticity output ----
        sens_map = {str(s.get("product_id", "")): s for s in sensitivities}
        price_map = {str(p.get("product_id", "")): p for p in optimal_prices}

        elasticity: list[dict[str, Any]] = []
        for product in products:
            pid = str(product.get("id", "unknown"))
            sens = sens_map.get(pid, {})
            opt = price_map.get(pid, {})

            elasticity.append({
                "product_id": pid,
                "coefficient": sens.get("elasticity_coefficient", 0.0),
                "optimal_price": opt.get("optimal_price", 0.0),
                "expected_revenue": opt.get("expected_revenue", 0.0),
                "is_elastic": sens.get("is_elastic", False),
            })

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_elasticity_result(elasticity=elasticity)

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "elasticity": elasticity,
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
