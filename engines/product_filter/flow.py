"""Product Filter Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Products → Margin Filter → Legal Filter → Shipping Filter →
  Brand Filter → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, criteria}, meta, error}
  Output: {status, data: {accepted_products, rejected_products, filter_summary}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .margin_filter import filter_by_margin
from .legal_filter import filter_by_legal
from .shipping_filter import filter_by_shipping
from .brand_filter import filter_by_brand
from .memory_reader import read_past_filters
from .memory_writer import write_filter_result
from engines._shopify_hydrator import hydrate


class ProductFilterEngine:
    """Product Filter Engine — orchestrator only, no logic."""

    ENGINE_NAME = "product_filter"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full product filter pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            FilterOutput dict.
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
        criteria = data.get("criteria", {})

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

        # ---- Stage 1: Read past filters (non-blocking) ----
        _past = read_past_filters(limit=5)

        # ---- Stage 2: Margin Filter ----
        margin_result = filter_by_margin(
            products=products,
            min_margin_pct=float(criteria.get("min_margin_pct", 15.0)),
        )
        if margin_result.get("status") == "error":
            return self._fail(
                f"Margin filter failed: {margin_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        margin_passed = margin_result.get("passed", [])
        margin_rejected = margin_result.get("rejected", [])

        # ---- Stage 3: Legal Filter ----
        legal_result = filter_by_legal(
            products=margin_passed,
            blocked_categories=list(criteria.get("blocked_categories", [])),
            allowed_countries=list(criteria.get("allowed_countries", [])),
        )
        if legal_result.get("status") == "error":
            return self._fail(
                f"Legal filter failed: {legal_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        legal_passed = legal_result.get("passed", [])
        legal_rejected = legal_result.get("rejected", [])

        # ---- Stage 4: Shipping Filter ----
        shipping_result = filter_by_shipping(
            products=legal_passed,
            max_weight_kg=float(criteria.get("max_weight_kg", 30.0)),
        )
        if shipping_result.get("status") == "error":
            return self._fail(
                f"Shipping filter failed: {shipping_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        shipping_passed = shipping_result.get("passed", [])
        shipping_rejected = shipping_result.get("rejected", [])

        # ---- Stage 5: Brand Filter ----
        brand_result = filter_by_brand(
            products=shipping_passed,
            blocked_brands=list(criteria.get("blocked_brands", [])),
            brand_profile=dict(criteria.get("brand_profile", {})),
        )
        if brand_result.get("status") == "error":
            return self._fail(
                f"Brand filter failed: {brand_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        brand_passed = brand_result.get("passed", [])
        brand_rejected = brand_result.get("rejected", [])

        # ---- Stage 6: Assemble rejections ----
        all_rejected = margin_rejected + legal_rejected + shipping_rejected + brand_rejected

        filter_summary: dict[str, Any] = {
            "total_input": len(products),
            "total_passed": len(brand_passed),
            "total_rejected": len(all_rejected),
            "margin_rejected": len(margin_rejected),
            "legal_rejected": len(legal_rejected),
            "shipping_rejected": len(shipping_rejected),
            "brand_rejected": len(brand_rejected),
        }

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_filter_result(
            accepted_products=brand_passed,
            rejected_products=all_rejected,
            filter_summary=filter_summary,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "accepted_products": brand_passed,
                "rejected_products": all_rejected,
                "filter_summary": filter_summary,
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
