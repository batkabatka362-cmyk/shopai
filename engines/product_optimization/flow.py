"""Product Optimization Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Performance Analyzer → Improvement Finder → Price Adjuster →
  Listing Enhancer → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, performance_data}, meta, error}
  Output: {status, data: {optimizations: [{product_id, type, recommendation, expected_impact}]}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .performance_analyzer import analyze_performance
from .improvement_finder import find_improvements
from .price_adjuster import adjust_prices
from .listing_enhancer import enhance_listings
from .memory_reader import read_past_optimizations
from .memory_writer import write_optimization_result
from engines._shopify_hydrator import hydrate


class ProductOptimizationEngine:
    """Product Optimization Engine — orchestrator only, no logic."""

    ENGINE_NAME = "product_optimization"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full optimization pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            OptimizationOutput dict.
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
        performance_data = data.get("performance_data", [])

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

        # ---- Stage 1: Read past optimizations (non-blocking) ----
        _past = read_past_optimizations(limit=5)

        # ---- Stage 2: Performance Analyzer ----
        perf_result = analyze_performance(
            products=products,
            performance_data=performance_data,
        )
        if perf_result.get("status") == "error":
            return self._fail(
                f"Performance analysis failed: {perf_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        analyses = perf_result.get("analyses", [])

        # ---- Stage 3: Improvement Finder ----
        improve_result = find_improvements(
            analyses=analyses,
            products=products,
        )
        if improve_result.get("status") == "error":
            return self._fail(
                f"Improvement finding failed: {improve_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        improvements = improve_result.get("improvements", [])

        # ---- Stage 4: Price Adjuster ----
        price_result = adjust_prices(
            products=products,
            performance_data=performance_data,
            analyses=analyses,
        )
        if price_result.get("status") == "error":
            return self._fail(
                f"Price adjustment failed: {price_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        adjustments = price_result.get("adjustments", [])

        # ---- Stage 5: Listing Enhancer ----
        listing_result = enhance_listings(
            products=products,
            analyses=analyses,
        )
        if listing_result.get("status") == "error":
            return self._fail(
                f"Listing enhancement failed: {listing_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        enhancements = listing_result.get("enhancements", [])

        # ---- Stage 6: Assemble optimizations ----
        optimizations: list[dict[str, Any]] = []

        for imp in improvements:
            optimizations.append({
                "product_id": imp.get("product_id", "unknown"),
                "type": imp.get("improvement_type", "general"),
                "recommendation": imp.get("recommendation", ""),
                "expected_impact": imp.get("expected_impact", 0.0),
            })

        for adj in adjustments:
            if abs(adj.get("adjustment_pct", 0.0)) > 0.1:
                optimizations.append({
                    "product_id": adj.get("product_id", "unknown"),
                    "type": "pricing",
                    "recommendation": f"{adj.get('rationale', '')} (suggested: ${adj.get('suggested_price', 0)})",
                    "expected_impact": round(abs(adj.get("adjustment_pct", 0.0)) / 100, 3),
                })

        for enh in enhancements:
            optimizations.append({
                "product_id": enh.get("product_id", "unknown"),
                "type": f"listing_{enh.get('enhancement_type', 'general')}",
                "recommendation": enh.get("suggestion", ""),
                "expected_impact": enh.get("expected_conversion_lift", 0.0),
            })

        # ---- Stage 6.5: Phase 7 writeback (opt-in) ----
        # Engines today emit advisory recommendations. When the
        # caller passes ``data.apply_pricing_adjustments = True``,
        # we enqueue the structured pricing adjustments via the
        # approval queue (operator review → executor →
        # SHOPIFY_UPDATE_VARIANTS). Default OFF preserves the
        # pure-recommendation behavior callers rely on.
        pricing_pending_actions: list[dict[str, Any]] = []
        if data.get("apply_pricing_adjustments") is True:
            from .optimization_applier import (
                apply_pricing_optimizations,
            )
            store_cfg = data.get("store") if isinstance(
                data.get("store"), dict,
            ) else None
            pricing_pending_actions = apply_pricing_optimizations(
                adjustments=adjustments,
                products=products,
                store=store_cfg,
            )

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_optimization_result(optimizations=optimizations)

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "optimizations": optimizations,
                # Phase 7 output. Empty list when not opted in;
                # populated with per-adjustment queue results
                # when ``apply_pricing_adjustments=True``.
                "pricing_pending_actions": pricing_pending_actions,
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
