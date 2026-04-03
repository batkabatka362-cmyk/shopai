"""SupplierDiscovery Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Search Engine → Qualification Checker → Cost Comparator → Recommendation Builder → Memory Writer → Output

Engine contract:
  Input:  {status, data: {product_requirements, regions, budget}, meta, error}
  Output: {status, data: {suppliers, recommended, comparison}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .search_engine import search_suppliers
from .qualification_checker import check_qualifications
from .cost_comparator import compare_costs
from .recommendation_builder import build_recommendations
from .memory_reader import read_past_results
from .memory_writer import write_result


class SupplierDiscoveryEngine:
    """SupplierDiscovery Engine — orchestrator only, no logic."""

    ENGINE_NAME = "supplier_discovery"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full supplier discovery pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            SupplierDiscoveryOutput dict.
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

        product_requirements = data.get("product_requirements", {})
        regions = data.get("regions", [])
        budget = data.get("budget", {})

        if not product_requirements:
            return self._fail("Product requirements are required", 0.0)

        # ---- Stage 1: Read past results (non-blocking) ----
        _past = read_past_results(limit=5)

        # ---- Stage 2: Search for potential suppliers ----
        search_engine_result = search_suppliers(
            product_requirements=product_requirements, regions=regions, budget=budget,
        )
        if search_engine_result.get("status") == "error":
            return self._fail(
                f"Search for potential suppliers failed: {search_engine_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        search_engine_data = search_engine_result.get("result", {})

        # ---- Stage 3: Check supplier qualifications ----
        qualification_checker_result = check_qualifications(
            product_requirements=product_requirements, regions=regions, budget=budget, search_engine_data=search_engine_data,
        )
        if qualification_checker_result.get("status") == "error":
            return self._fail(
                f"Check supplier qualifications failed: {qualification_checker_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        qualification_checker_data = qualification_checker_result.get("result", {})

        # ---- Stage 4: Compare costs across suppliers ----
        cost_comparator_result = compare_costs(
            product_requirements=product_requirements, regions=regions, budget=budget, search_engine_data=search_engine_data, qualification_checker_data=qualification_checker_data,
        )
        if cost_comparator_result.get("status") == "error":
            return self._fail(
                f"Compare costs across suppliers failed: {cost_comparator_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        cost_comparator_data = cost_comparator_result.get("result", {})

        # ---- Stage 5: Build supplier recommendations ----
        recommendation_builder_result = build_recommendations(
            product_requirements=product_requirements, regions=regions, budget=budget, search_engine_data=search_engine_data, qualification_checker_data=qualification_checker_data, cost_comparator_data=cost_comparator_data,
        )
        if recommendation_builder_result.get("status") == "error":
            return self._fail(
                f"Build supplier recommendations failed: {recommendation_builder_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        recommendation_builder_data = recommendation_builder_result.get("result", {})

        # ---- Memory Writer (non-fatal) ----
        output_data = {
                "suppliers": recommendation_builder_data.get("suppliers", []),
                "recommended": recommendation_builder_data.get("recommended", []),
                "comparison": recommendation_builder_data.get("comparison", {}),
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
