"""Dropshipping Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Supplier Matcher → Auto Orderer → Tracking Syncer →
  Margin Optimizer → Memory Writer → Output

Engine contract:
  Input:  {status, data: {orders, suppliers, products, tracking_data}, meta, error}
  Output: {status, data: {supplier_orders, tracking_updates, margin_analysis, supplier_performance}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .supplier_matcher import match_suppliers
from .auto_orderer import auto_create_orders
from .tracking_syncer import sync_tracking
from .margin_optimizer import optimize_margins
from .memory_reader import read_past_dropshipping
from .memory_writer import write_dropshipping_result
from engines._shopify_hydrator import hydrate


class DropshippingEngine:
    """Dropshipping Engine — orchestrator only, no logic."""

    ENGINE_NAME = "dropshipping"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(payload.get("error", "Upstream failure"), 0.0)

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        orders = data.get("orders", [])
        suppliers = data.get("suppliers", [])
        products = data.get("products", [])
        tracking_data = data.get("tracking_data", [])

        # Auto-hydrate orders from Shopify when caller left the
        # list empty. Pre-existing failure semantics preserved:
        # empty supplied AND empty hydrated → standard error.
        orders = hydrate(
            supplied=orders if isinstance(orders, list) else [],
            capability_name="SHOPIFY_FETCH_ORDERS",
            list_field="orders",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not orders:
            return self._fail("Orders list is required", 0.0)

        _past = read_past_dropshipping(limit=5)

        # Stage 1: Supplier Matcher
        match_result = match_suppliers(products=products, suppliers=suppliers, orders=orders)
        if match_result.get("status") == "error":
            return self._fail(f"Supplier matching failed: {match_result.get('error', 'unknown')}", time.monotonic() - start)
        supplier_orders = match_result.get("supplier_orders", [])

        # Stage 2: Auto Orderer
        auto_result = auto_create_orders(supplier_orders=supplier_orders)
        if auto_result.get("status") == "error":
            return self._fail(f"Auto ordering failed: {auto_result.get('error', 'unknown')}", time.monotonic() - start)
        supplier_orders = auto_result.get("supplier_orders", [])

        # Stage 3: Tracking Syncer
        track_result = sync_tracking(supplier_orders=supplier_orders, tracking_data=tracking_data)
        if track_result.get("status") == "error":
            return self._fail(f"Tracking sync failed: {track_result.get('error', 'unknown')}", time.monotonic() - start)
        tracking_updates = track_result.get("tracking_updates", [])

        # Stage 4: Margin Optimizer
        margin_result = optimize_margins(supplier_orders=supplier_orders, products=products, suppliers=suppliers)
        if margin_result.get("status") == "error":
            return self._fail(f"Margin optimization failed: {margin_result.get('error', 'unknown')}", time.monotonic() - start)
        margin_analysis = margin_result.get("margin_analysis", [])
        supplier_performance = margin_result.get("supplier_performance", [])

        # Stage 5: Memory Writer (non-fatal)
        _write_result = write_dropshipping_result(
            supplier_orders=supplier_orders, tracking_updates=tracking_updates,
            margin_analysis=margin_analysis, supplier_performance=supplier_performance,
        )

        # Phase 7: optional thin-margin tag apply. Opt-in via
        # data.apply_thin_margin_tags=True. Tags products at
        # margin_pct < 25 via SHOPIFY_UPDATE_PRODUCT.
        tagged_thin_margin: list[dict[str, Any]] = []
        if bool(data.get("apply_thin_margin_tags")):
            try:
                from .tag_applier import apply_thin_margin_tags
                tagged_thin_margin = apply_thin_margin_tags(
                    margin_analysis, products,
                )
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).debug(
                    "dropshipping: apply loop raised: %s", exc,
                )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "supplier_orders": supplier_orders,
                "tracking_updates": tracking_updates,
                "margin_analysis": margin_analysis,
                "supplier_performance": supplier_performance,
                "tagged_thin_margin": tagged_thin_margin,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        return {
            "status": "error", "data": None,
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": reason,
        }
