"""CompetitionAnalyzer Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Price Comparator → Positioning Analyzer → Strength Mapper → Share Estimator → Memory Writer → Output

Engine contract:
  Input:  {status, data: {competitors, products, market_data}, meta, error}
  Output: {status, data: {analysis, threats, opportunities}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .price_comparator import compare_prices
from .positioning_analyzer import analyze_positioning
from .strength_mapper import map_strengths
from .share_estimator import estimate_share
from .memory_reader import read_past_results
from .memory_writer import write_result
from engines._shopify_hydrator import hydrate


class CompetitionAnalyzerEngine:
    """CompetitionAnalyzer Engine — orchestrator only, no logic."""

    ENGINE_NAME = "competition_analyzer"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full competition analyzer pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            CompetitionAnalyzerOutput dict.
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
        products = data.get("products", [])
        market_data = data.get("market_data", {})

        # Auto-hydrate products from Shopify when caller left the
        # list empty. products is auxiliary (competitors is gated),
        # but feeds price comparison + positioning analysis.
        products = hydrate(
            supplied=products if isinstance(products, list) else [],
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not competitors:
            return self._fail("Competitors list is required", 0.0)

        # ---- Stage 1: Read past results (non-blocking) ----
        _past = read_past_results(limit=5)

        # ---- Stage 2: Compare pricing across competitors ----
        price_comparator_result = compare_prices(
            competitors=competitors, products=products, market_data=market_data,
        )
        if price_comparator_result.get("status") == "error":
            return self._fail(
                f"Compare pricing across competitors failed: {price_comparator_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        price_comparator_data = price_comparator_result.get("result", {})

        # ---- Stage 3: Analyze market positioning ----
        positioning_analyzer_result = analyze_positioning(
            competitors=competitors, products=products, market_data=market_data, price_comparator_data=price_comparator_data,
        )
        if positioning_analyzer_result.get("status") == "error":
            return self._fail(
                f"Analyze market positioning failed: {positioning_analyzer_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        positioning_analyzer_data = positioning_analyzer_result.get("result", {})

        # ---- Stage 4: Map competitor strengths/weaknesses ----
        strength_mapper_result = map_strengths(
            competitors=competitors, products=products, market_data=market_data, price_comparator_data=price_comparator_data, positioning_analyzer_data=positioning_analyzer_data,
        )
        if strength_mapper_result.get("status") == "error":
            return self._fail(
                f"Map competitor strengths/weaknesses failed: {strength_mapper_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        strength_mapper_data = strength_mapper_result.get("result", {})

        # ---- Stage 5: Estimate market share ----
        share_estimator_result = estimate_share(
            competitors=competitors, products=products, market_data=market_data, price_comparator_data=price_comparator_data, positioning_analyzer_data=positioning_analyzer_data, strength_mapper_data=strength_mapper_data,
        )
        if share_estimator_result.get("status") == "error":
            return self._fail(
                f"Estimate market share failed: {share_estimator_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        share_estimator_data = share_estimator_result.get("result", {})

        # ---- Memory Writer (non-fatal) ----
        output_data = {
                "analysis": share_estimator_data.get("analysis", []),
                "threats": share_estimator_data.get("threats", []),
                "opportunities": share_estimator_data.get("opportunities", []),
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
