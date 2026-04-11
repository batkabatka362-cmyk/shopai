"""CompetitorAnalysis Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Strategy Detector → Price Tracker → Product Tracker → Alert Builder → Memory Writer → Output

Engine contract:
  Input:  {status, data: {competitors, tracked_products}, meta, error}
  Output: {status, data: {strategies, price_changes, new_products, alerts}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .strategy_detector import detect_strategies
from .price_tracker import track_prices
from .product_tracker import track_products
from .alert_builder import build_alerts
from .memory_reader import read_past_results
from .memory_writer import write_result


class CompetitorAnalysisEngine:
    """CompetitorAnalysis Engine — orchestrator only, no logic."""

    ENGINE_NAME = "competitor_analysis"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full competitor analysis pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            CompetitorAnalysisOutput dict.
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

        competitors = data.get("competitors", [])
        tracked_products = data.get("tracked_products", [])

        if not competitors:
            return self._fail("Competitors list is required", 0.0)

        # ---- Stage 1: Read past results (non-blocking) ----
        _past = read_past_results(limit=5)

        # ---- Stage 2: Detect competitor strategies ----
        strategy_detector_result = detect_strategies(
            competitors=competitors, tracked_products=tracked_products,
        )
        if strategy_detector_result.get("status") == "error":
            return self._fail(
                f"Detect competitor strategies failed: {strategy_detector_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        strategy_detector_data = strategy_detector_result.get("result", {})

        # ---- Stage 3: Track competitor prices ----
        price_tracker_result = track_prices(
            competitors=competitors, tracked_products=tracked_products, strategy_detector_data=strategy_detector_data,
        )
        if price_tracker_result.get("status") == "error":
            return self._fail(
                f"Track competitor prices failed: {price_tracker_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        price_tracker_data = price_tracker_result.get("result", {})

        # ---- Stage 4: Track competitor product launches ----
        product_tracker_result = track_products(
            competitors=competitors, tracked_products=tracked_products, strategy_detector_data=strategy_detector_data, price_tracker_data=price_tracker_data,
        )
        if product_tracker_result.get("status") == "error":
            return self._fail(
                f"Track competitor product launches failed: {product_tracker_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        product_tracker_data = product_tracker_result.get("result", {})

        # ---- Stage 5: Build competitive alerts ----
        alert_builder_result = build_alerts(
            competitors=competitors, tracked_products=tracked_products, strategy_detector_data=strategy_detector_data, price_tracker_data=price_tracker_data, product_tracker_data=product_tracker_data,
        )
        if alert_builder_result.get("status") == "error":
            return self._fail(
                f"Build competitive alerts failed: {alert_builder_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        alert_builder_data = alert_builder_result.get("result", {})

        # ---- Memory Writer (non-fatal) ----
        output_data = {
                "strategies": alert_builder_data.get("strategies", []),
                "price_changes": alert_builder_data.get("price_changes", []),
                "new_products": alert_builder_data.get("new_products", []),
                "alerts": alert_builder_data.get("alerts", []),
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
