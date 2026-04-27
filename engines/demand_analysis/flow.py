"""DemandAnalysis Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Volume Estimator → Velocity Calculator → Segment Decomposer → Saturation Checker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {market_data, products, segments}, meta, error}
  Output: {status, data: {demand, segments, saturation_level}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .volume_estimator import estimate_volume
from .velocity_calculator import calculate_velocity
from .segment_decomposer import decompose_segments
from .saturation_checker import check_saturation
from .memory_reader import read_past_results
from .memory_writer import write_result
from engines._shopify_hydrator import hydrate


class DemandAnalysisEngine:
    """DemandAnalysis Engine — orchestrator only, no logic."""

    ENGINE_NAME = "demand_analysis"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full demand analysis pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            DemandAnalysisOutput dict.
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

        market_data = data.get("market_data", {})
        products = data.get("products", [])
        segments = data.get("segments", [])

        # Auto-hydrate products from Shopify when caller left the
        # list empty. products is auxiliary (market_data is gated),
        # but feeds volume + velocity estimators.
        products = hydrate(
            supplied=products if isinstance(products, list) else [],
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not market_data:
            return self._fail("Market data is required", 0.0)

        # ---- Stage 1: Read past results (non-blocking) ----
        _past = read_past_results(limit=5)

        # ---- Stage 2: Estimate demand volume ----
        volume_estimator_result = estimate_volume(
            market_data=market_data, products=products, segments=segments,
        )
        if volume_estimator_result.get("status") == "error":
            return self._fail(
                f"Estimate demand volume failed: {volume_estimator_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        volume_estimator_data = volume_estimator_result.get("result", {})

        # ---- Stage 3: Calculate demand velocity ----
        velocity_calculator_result = calculate_velocity(
            market_data=market_data, products=products, segments=segments, volume_estimator_data=volume_estimator_data,
        )
        if velocity_calculator_result.get("status") == "error":
            return self._fail(
                f"Calculate demand velocity failed: {velocity_calculator_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        velocity_calculator_data = velocity_calculator_result.get("result", {})

        # ---- Stage 4: Decompose demand by segment ----
        segment_decomposer_result = decompose_segments(
            market_data=market_data, products=products, segments=segments, volume_estimator_data=volume_estimator_data, velocity_calculator_data=velocity_calculator_data,
        )
        if segment_decomposer_result.get("status") == "error":
            return self._fail(
                f"Decompose demand by segment failed: {segment_decomposer_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        segment_decomposer_data = segment_decomposer_result.get("result", {})

        # ---- Stage 5: Check market saturation ----
        saturation_checker_result = check_saturation(
            market_data=market_data, products=products, segments=segments, volume_estimator_data=volume_estimator_data, velocity_calculator_data=velocity_calculator_data, segment_decomposer_data=segment_decomposer_data,
        )
        if saturation_checker_result.get("status") == "error":
            return self._fail(
                f"Check market saturation failed: {saturation_checker_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        saturation_checker_data = saturation_checker_result.get("result", {})

        # ---- Memory Writer (non-fatal) ----
        output_data = {
                "demand": saturation_checker_data.get("demand", {}),
                "segments": saturation_checker_data.get("segments", []),
                "saturation_level": saturation_checker_data.get("saturation_level", 0.0),
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
