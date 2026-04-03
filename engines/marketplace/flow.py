"""Marketplace Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input Data → Memory Reader → Listing Syncer → Price Harmonizer →
  Performance Comparator → Inventory Allocator → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, marketplaces, inventory, pricing}, meta, error}
  Output: {status, data: {sync_status, price_adjustments, inventory_allocation, performance}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .listing_syncer import sync_listings
from .price_harmonizer import harmonize_prices
from .inventory_allocator import allocate_inventory
from .performance_comparator import compare_performance
from .memory_reader import read_past_marketplace
from .memory_writer import write_marketplace_result


class MarketplaceEngine:
    """Marketplace Engine — orchestrator only, no logic."""

    ENGINE_NAME = "marketplace"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full marketplace pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            MarketplaceOutput dict.
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
        marketplaces = data.get("marketplaces", [])
        inventory = data.get("inventory", {})
        pricing = data.get("pricing", {})

        if not products:
            return self._fail("Product list is required", 0.0)
        if not marketplaces:
            return self._fail("Marketplace list is required", 0.0)

        # ---- Stage 1: Read past marketplace data (non-blocking) ----
        _past = read_past_marketplace(limit=5)

        # ---- Stage 2: Listing Syncer ----
        sync_result = sync_listings(
            products=products,
            marketplaces=marketplaces,
        )
        if sync_result.get("status") == "error":
            return self._fail(
                f"Listing sync failed: {sync_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        sync_status = sync_result.get("sync_results", [])

        # ---- Stage 3: Price Harmonizer ----
        price_result = harmonize_prices(
            products=products,
            marketplaces=marketplaces,
            pricing=pricing,
        )
        if price_result.get("status") == "error":
            return self._fail(
                f"Price harmonization failed: {price_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        price_adjustments = price_result.get("adjustments", [])

        # ---- Stage 4: Performance Comparator ----
        perf_result = compare_performance(
            products=products,
            marketplaces=marketplaces,
            sync_results=sync_status,
        )
        if perf_result.get("status") == "error":
            return self._fail(
                f"Performance comparison failed: {perf_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        performance = perf_result.get("performance", [])

        # ---- Stage 5: Inventory Allocator ----
        alloc_result = allocate_inventory(
            products=products,
            marketplaces=marketplaces,
            inventory=inventory,
            performance=performance,
        )
        if alloc_result.get("status") == "error":
            return self._fail(
                f"Inventory allocation failed: {alloc_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        inventory_allocation = alloc_result.get("allocations", [])

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_marketplace_result(
            sync_status=sync_status,
            price_adjustments=price_adjustments,
            inventory_allocation=inventory_allocation,
            performance=performance,
        )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "sync_status": sync_status,
                "price_adjustments": price_adjustments,
                "inventory_allocation": inventory_allocation,
                "performance": performance,
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
