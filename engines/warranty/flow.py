"""Warranty Engine — flow orchestrator.

Pipeline:
  Input → Memory Reader → Policy Manager → Claim Processor →
  Cost Tracker → Risk Analyzer → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, claims, policies}, meta, error}
  Output: {status, data: {claims_processed, costs, risk_analysis, policy_recommendations}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .policy_manager import manage_policies
from .claim_processor import process_claims
from .cost_tracker import track_costs
from .risk_analyzer import analyze_risk
from .memory_reader import read_past_warranty
from .memory_writer import write_warranty_result
from engines._shopify_hydrator import hydrate


class WarrantyEngine:
    """Warranty Engine — orchestrator only, no logic."""

    ENGINE_NAME = "warranty"

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
        claims = data.get("claims", [])
        policies = data.get("policies", [])

        # Auto-hydrate products from Shopify when caller left the
        # list empty. Pre-existing failure semantics preserved:
        # OR-gate fires only if both products+claims are empty
        # after hydration.
        products = hydrate(
            supplied=products if isinstance(products, list) else [],
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not products and not claims:
            return self._fail("Products or claims required", 0.0)

        _past = read_past_warranty(limit=5)

        _pol_result = manage_policies(products=products, policies=policies)

        claim_result = process_claims(claims=claims, policies=policies)
        if claim_result.get("status") == "error":
            return self._fail(f"Claim processing failed: {claim_result.get('error')}", time.monotonic() - start)
        claims_processed = claim_result.get("claims_processed", {})

        cost_result = track_costs(claims_processed=claims_processed, products=products)
        if cost_result.get("status") == "error":
            return self._fail(f"Cost tracking failed: {cost_result.get('error')}", time.monotonic() - start)
        costs = cost_result.get("costs", {})

        risk_result = analyze_risk(claims_processed=claims_processed, products=products, costs=costs)
        if risk_result.get("status") == "error":
            return self._fail(f"Risk analysis failed: {risk_result.get('error')}", time.monotonic() - start)
        risk_analysis = risk_result.get("risk_analysis", [])
        policy_recommendations = risk_result.get("policy_recommendations", [])

        _write = write_warranty_result(claims_processed=claims_processed, costs=costs)

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "claims_processed": claims_processed,
                "costs": costs,
                "risk_analysis": risk_analysis,
                "policy_recommendations": policy_recommendations,
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
