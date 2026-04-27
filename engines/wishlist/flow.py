"""Wishlist Engine — flow orchestrator.

Pipeline:
  Input → Memory Reader → Wishlist Analyzer → Price Alert Manager →
  Conversion Optimizer → Social Proof Builder → Memory Writer → Output

Engine contract:
  Input:  {status, data: {wishlists, products, customers}, meta, error}
  Output: {status, data: {analysis, price_alerts, conversion_recommendations, social_proof_data}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .wishlist_analyzer import analyze_wishlists
from .price_alert_manager import manage_price_alerts
from .conversion_optimizer import optimize_conversion
from .social_proof_builder import build_social_proof
from .memory_reader import read_past_wishlist
from .memory_writer import write_wishlist_result
from engines._shopify_hydrator import hydrate


class WishlistEngine:
    """Wishlist Engine — orchestrator only, no logic."""

    ENGINE_NAME = "wishlist"

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

        wishlists = data.get("wishlists", [])
        products = data.get("products", [])
        customers = data.get("customers", [])

        # Auto-hydrate products + customers from Shopify when caller
        # left the lists empty. Both are auxiliary (wishlists is
        # gated), but feed downstream analysis + social proof.
        hydrate_limit = data.get("hydrate_limit")
        hydrate_query = data.get("hydrate_query")
        products = hydrate(
            supplied=products if isinstance(products, list) else [],
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            limit=hydrate_limit,
            query=hydrate_query,
        )
        customers = hydrate(
            supplied=customers if isinstance(customers, list) else [],
            capability_name="SHOPIFY_FETCH_CUSTOMERS",
            list_field="customers",
            limit=hydrate_limit,
            query=hydrate_query,
        )

        if not wishlists:
            return self._fail("Wishlists list is required", 0.0)

        _past = read_past_wishlist(limit=5)

        wl_result = analyze_wishlists(wishlists=wishlists, products=products)
        if wl_result.get("status") == "error":
            return self._fail(f"Wishlist analysis failed: {wl_result.get('error')}", time.monotonic() - start)
        analysis = wl_result.get("analysis", {})

        alert_result = manage_price_alerts(wishlists=wishlists, products=products)
        if alert_result.get("status") == "error":
            return self._fail(f"Price alert management failed: {alert_result.get('error')}", time.monotonic() - start)
        price_alerts = alert_result.get("price_alerts", [])

        conv_result = optimize_conversion(wishlists=wishlists, products=products, analysis=analysis)
        if conv_result.get("status") == "error":
            return self._fail(f"Conversion optimization failed: {conv_result.get('error')}", time.monotonic() - start)
        conversion_recommendations = conv_result.get("recommendations", [])

        sp_result = build_social_proof(analysis=analysis, products=products)
        if sp_result.get("status") == "error":
            return self._fail(f"Social proof building failed: {sp_result.get('error')}", time.monotonic() - start)
        social_proof_data = sp_result.get("social_proof", {})

        _write = write_wishlist_result(analysis=analysis, recommendations_count=len(conversion_recommendations))

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "analysis": analysis,
                "price_alerts": price_alerts,
                "conversion_recommendations": conversion_recommendations,
                "social_proof_data": social_proof_data,
            },
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": None,
        }

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        return {
            "status": "error", "data": None,
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": reason,
        }
