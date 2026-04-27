"""DemandEstimator Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Base Estimator → Adjustment Calculator → Confidence Builder → Scenario Modeler → Memory Writer → Output

Engine contract:
  Input:  {status, data: {product, market_size, competition, seasonality}, meta, error}
  Output: {status, data: {estimate, confidence, scenarios}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .base_estimator import estimate_base
from .adjustment_calculator import calculate_adjustments
from .confidence_builder import build_confidence
from .scenario_modeler import model_scenarios
from .memory_reader import read_past_results
from .memory_writer import write_result
from engines._shopify_hydrator import hydrate_one


class DemandEstimatorEngine:
    """DemandEstimator Engine — orchestrator only, no logic."""

    ENGINE_NAME = "demand_estimator"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full demand estimator pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            DemandEstimatorOutput dict.
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

        product = data.get("product", {})
        market_size = float(data.get("market_size", 0.0))
        competition = data.get("competition", {})
        seasonality = data.get("seasonality", {})

        # Auto-hydrate a single product from Shopify when caller
        # left the dict empty. Pre-existing failure semantics
        # preserved: empty supplied AND empty hydrated → standard
        # error.
        product = hydrate_one(
            supplied=product if isinstance(product, dict) else {},
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            query=data.get("hydrate_query"),
        )

        if not product:
            return self._fail("Product data is required", 0.0)

        # ---- Stage 1: Read past results (non-blocking) ----
        _past = read_past_results(limit=5)

        # ---- Stage 2: Estimate base demand from market size ----
        base_estimator_result = estimate_base(
            product=product, market_size=market_size, competition=competition, seasonality=seasonality,
        )
        if base_estimator_result.get("status") == "error":
            return self._fail(
                f"Estimate base demand from market size failed: {base_estimator_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        base_estimator_data = base_estimator_result.get("result", {})

        # ---- Stage 3: Adjust for competition, seasonality ----
        adjustment_calculator_result = calculate_adjustments(
            product=product, market_size=market_size, competition=competition, seasonality=seasonality, base_estimator_data=base_estimator_data,
        )
        if adjustment_calculator_result.get("status") == "error":
            return self._fail(
                f"Adjust for competition, seasonality failed: {adjustment_calculator_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        adjustment_calculator_data = adjustment_calculator_result.get("result", {})

        # ---- Stage 4: Build confidence intervals ----
        confidence_builder_result = build_confidence(
            product=product, market_size=market_size, competition=competition, seasonality=seasonality, base_estimator_data=base_estimator_data, adjustment_calculator_data=adjustment_calculator_data,
        )
        if confidence_builder_result.get("status") == "error":
            return self._fail(
                f"Build confidence intervals failed: {confidence_builder_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        confidence_builder_data = confidence_builder_result.get("result", {})

        # ---- Stage 5: Model best/worst/expected scenarios ----
        scenario_modeler_result = model_scenarios(
            product=product, market_size=market_size, competition=competition, seasonality=seasonality, base_estimator_data=base_estimator_data, adjustment_calculator_data=adjustment_calculator_data, confidence_builder_data=confidence_builder_data,
        )
        if scenario_modeler_result.get("status") == "error":
            return self._fail(
                f"Model best/worst/expected scenarios failed: {scenario_modeler_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        scenario_modeler_data = scenario_modeler_result.get("result", {})

        # ---- Memory Writer (non-fatal) ----
        output_data = {
                "estimate": scenario_modeler_data.get("estimate", {}),
                "confidence": scenario_modeler_data.get("confidence", 0.0),
                "scenarios": scenario_modeler_data.get("scenarios", {}),
        }
        _write_result = write_result(output_data=output_data)

        # ---- Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": output_data,
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
