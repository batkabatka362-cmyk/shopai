"""Monetization Engine — flow orchestrator.

Pipeline:
  Input → Memory Reader → Revenue Scanner → Subscription Evaluator →
  Upsell Mapper → Pricing Advisor → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, customers, revenue_data}, meta, error}
  Output: {status, data: {opportunities, recommended_models, projected_uplift}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .revenue_scanner import scan_revenue
from .subscription_evaluator import evaluate_subscriptions
from .upsell_mapper import map_upsells
from .pricing_advisor import advise_pricing
from .memory_reader import read_past_monetization
from .memory_writer import write_monetization_result
from engines._shopify_hydrator import hydrate


class MonetizationEngine:
    """Monetization Engine — orchestrator only, no logic."""

    ENGINE_NAME = "monetization"

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

        products = data.get("products", [])
        customers = data.get("customers", [])
        revenue_data = data.get("revenue_data", {})

        # Auto-hydrate products + customers from Shopify when caller
        # left the lists empty. Both feed downstream stages.
        # Pre-existing failure semantics preserved: empty supplied
        # AND empty hydrated → standard error.
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

        if not products:
            return self._fail("Products list is required", 0.0)

        _past = read_past_monetization(limit=5)

        # ---- Revenue Scanner ----
        scan_result = scan_revenue(products=products, customers=customers, revenue_data=revenue_data)
        if scan_result.get("status") == "error":
            return self._fail(f"Revenue scanning failed: {scan_result.get('error')}", time.monotonic() - start)
        opportunities = scan_result.get("opportunities", [])

        # ---- Subscription Evaluator ----
        sub_result = evaluate_subscriptions(products=products, customers=customers)
        if sub_result.get("status") == "error":
            return self._fail(f"Subscription evaluation failed: {sub_result.get('error')}", time.monotonic() - start)
        if sub_result.get("subscription_viable"):
            opportunities.append({
                "type": "subscription",
                "potential_revenue": sum(c.get("monthly_revenue_potential", 0) for c in sub_result.get("candidates", [])),
                "effort": "high",
                "description": f"{sub_result.get('total_candidates', 0)} products suitable for subscription model",
            })

        # ---- Upsell Mapper ----
        upsell_result = map_upsells(products=products, revenue_data=revenue_data)
        if upsell_result.get("status") == "error":
            return self._fail(f"Upsell mapping failed: {upsell_result.get('error')}", time.monotonic() - start)
        if upsell_result.get("total_upsells", 0) > 0:
            opportunities.append({
                "type": "upsell",
                "potential_revenue": upsell_result.get("total_potential_uplift", 0),
                "effort": "medium",
                "description": f"{upsell_result.get('total_upsells', 0)} upsell paths identified",
            })

        # ---- Pricing Advisor ----
        pricing_result = advise_pricing(products=products, revenue_data=revenue_data)
        if pricing_result.get("status") == "error":
            return self._fail(f"Pricing advisory failed: {pricing_result.get('error')}", time.monotonic() - start)
        recommended_models = pricing_result.get("recommended_models", [])
        projected_uplift = pricing_result.get("projected_uplift_pct", 0.0)

        # Add total potential from all opportunities
        total_potential = sum(o.get("potential_revenue", 0) for o in opportunities)
        projected_uplift = round(projected_uplift + (total_potential / max(float(revenue_data.get("total_revenue", 1)), 1)) * 100, 1)

        _write = write_monetization_result(
            opportunities=opportunities, recommended_models=recommended_models, projected_uplift=projected_uplift,
        )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "opportunities": opportunities,
                "recommended_models": recommended_models,
                "projected_uplift": projected_uplift,
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
