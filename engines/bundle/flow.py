"""Bundle Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Memory Reader → Affinity Analyzer → Bundle Generator →
  Price Optimizer → Cannibalization Checker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, orders, pricing_data, constraints}, meta, error}
  Output: {status, data: {bundles, best_bundle, cannibalization_risk}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .affinity_analyzer import analyze_affinity
from .bundle_generator import generate_bundles
from .price_optimizer import optimize_prices
from .cannibalization_checker import check_cannibalization
from .bundle_applier import (
    apply_bundle_product,
    enqueue_bundle_for_approval,
)
from .memory_reader import read_past_bundles
from .memory_writer import write_bundle_result
from .shopify_hydrator import hydrate_products, hydrate_orders


class BundleEngine:
    """Bundle Engine — orchestrator only, no logic."""

    ENGINE_NAME = "bundle"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full bundle pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            BundleOutput dict.
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
        orders = data.get("orders", [])
        pricing_data = data.get("pricing_data", {})
        constraints = data.get("constraints", {})

        # ---- Stage 0.5: Auto-hydrate from Shopify when caller
        # didn't pre-fetch. No-op if products / orders are already
        # populated. If the router is unavailable / Shopify is
        # unreachable / scopes are missing, returns whatever was
        # supplied (empty if nothing) — the standard "Product list
        # is required" check below still fires.
        hydrate_limit = data.get("hydrate_limit")
        hydrate_query = data.get("hydrate_query")
        products = hydrate_products(
            products,
            limit=hydrate_limit,
            query=hydrate_query,
        )
        orders = hydrate_orders(
            orders,
            limit=hydrate_limit,
        )

        if not products:
            return self._fail("Product list is required", 0.0)

        # ---- Stage 1: Read past bundles (non-blocking) ----
        _past = read_past_bundles(limit=5)

        # ---- Stage 2: Affinity Analyzer ----
        affinity_result = analyze_affinity(
            orders=orders,
            products=products,
        )
        if affinity_result.get("status") == "error":
            return self._fail(
                f"Affinity analysis failed: {affinity_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        affinities = affinity_result.get("affinities", [])

        # ---- Stage 3: Bundle Generator ----
        generator_result = generate_bundles(
            products=products,
            affinities=affinities,
            constraints=constraints,
        )
        if generator_result.get("status") == "error":
            return self._fail(
                f"Bundle generation failed: {generator_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        generated = generator_result.get("bundles", [])

        # ---- Stage 4: Price Optimizer ----
        optimizer_result = optimize_prices(
            bundles=generated,
            products=products,
            pricing_data=pricing_data,
        )
        if optimizer_result.get("status") == "error":
            return self._fail(
                f"Price optimization failed: {optimizer_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        optimized = optimizer_result.get("optimized", [])

        # ---- Stage 5: Cannibalization Checker ----
        cannibal_result = check_cannibalization(
            optimized_bundles=optimized,
            products=products,
        )
        if cannibal_result.get("status") == "error":
            return self._fail(
                f"Cannibalization check failed: {cannibal_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        cannibalization_risk = cannibal_result.get("results", [])

        # ---- Stage 6: Assemble output bundles ----
        # Carry ``product_ids`` and ``bundle_id`` through to the
        # output so downstream consumers (the Stage 6.5 applier,
        # the executor's bundle dispatcher) can resolve component
        # ids without re-running the optimizer. ``products`` (the
        # titles list) is preserved for backwards compat.
        bundles: list[dict[str, Any]] = []
        for opt in optimized:
            bundles.append({
                "bundle_id": opt.get("bundle_id", ""),
                "products": opt.get("product_titles", []),
                "product_ids": opt.get("product_ids", []),
                "product_titles": opt.get("product_titles", []),
                "bundle_price": opt.get("bundle_price", 0.0),
                "savings_pct": opt.get("savings_pct", 0.0),
                "estimated_uplift": opt.get("estimated_uplift", 0.0),
                "margin": opt.get("margin", 0.0),
            })

        best_bundle = bundles[0] if bundles else None

        # ---- Stage 6.5: Bundle-product writeback (opt-in) ----
        # Default OFF — existing callers keep their pure-
        # recommendation contract. Two opt-in modes mirror the
        # established Phase 6/7 pattern:
        #
        #   data.apply_bundle=True + data.require_approval=False
        #     → SHOPIFY_CREATE_PRODUCT immediately
        #   data.apply_bundle=True + data.require_approval=True
        #     → enqueue to core.approval; merchant approves before
        #       the mutation lands
        #
        # Both paths share the same upfront guards (>=2 components,
        # positive savings, cannibalization recommendation isn't
        # "reconsider_bundle"). The product is created as DRAFT —
        # component-tracking via the Shopify Bundles app isn't in
        # the adapter layer yet, so the merchant finishes the
        # wiring before publishing.
        bundle_apply_result: dict[str, Any] | None = None
        bundle_pending_action: dict[str, Any] | None = None
        store_cfg = data.get("store", {}) if isinstance(
            data.get("store"), dict,
        ) else {}
        if data.get("apply_bundle") is True:
            if data.get("require_approval") is True:
                bundle_pending_action = enqueue_bundle_for_approval(
                    best_bundle=best_bundle,
                    cannibalization_risk=cannibalization_risk,
                    store=store_cfg,
                )
            else:
                bundle_apply_result = apply_bundle_product(
                    best_bundle=best_bundle,
                    cannibalization_risk=cannibalization_risk,
                    store=store_cfg,
                )

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_bundle_result(
            bundles=bundles,
            best_bundle=best_bundle,
            cannibalization_risk=cannibalization_risk,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "bundles": bundles,
                "best_bundle": best_bundle,
                "cannibalization_risk": cannibalization_risk,
                # Stage 6.5 output — mutually exclusive: one or
                # the other is populated when the opt-in flags
                # routed through a path; both ``None`` when
                # default-off or guardrails rejected.
                "bundle_apply_result": bundle_apply_result,
                "bundle_pending_action": bundle_pending_action,
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
