"""Cohort Analysis Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Cohort Builder → Retention Calculator → Revenue Tracker →
  LTV Projector → Memory Writer → Output

Engine contract:
  Input:  {status, data: {customers, orders, cohort_type}, meta, error}
  Output: {status, data: {cohorts, retention_matrix, best_cohort, trends}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .cohort_builder import build_cohorts
from .retention_calculator import calculate_retention
from .revenue_tracker import track_revenue
from .ltv_projector import project_ltv
from .memory_reader import read_past_cohorts
from .memory_writer import write_cohort_result
from .shopify_hydrator import hydrate_customers, hydrate_orders


class CohortAnalysisEngine:
    """Cohort Analysis Engine — orchestrator only, no logic."""

    ENGINE_NAME = "cohort_analysis"

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

        customers = data.get("customers", [])
        orders = data.get("orders", [])
        cohort_type = str(data.get("cohort_type", "monthly"))

        # Stage 0.5: Auto-hydrate from Shopify when caller didn't
        # pre-fetch. Pass-through if either list is non-empty;
        # auto-fetch via Capability.SHOPIFY_FETCH_CUSTOMERS /
        # SHOPIFY_FETCH_ORDERS otherwise. Optional ``hydrate_limit``
        # / ``hydrate_query`` on the input data block scope the
        # auto-fetch (e.g. ``"created_at:>2025-01-01"``).
        hydrate_limit = data.get("hydrate_limit")
        hydrate_query = data.get("hydrate_query")
        customers = hydrate_customers(
            customers, limit=hydrate_limit, query=hydrate_query,
        )
        orders = hydrate_orders(
            orders, limit=hydrate_limit, query=hydrate_query,
        )

        if not customers and not orders:
            return self._fail("Customers or orders list is required", 0.0)

        _past = read_past_cohorts(limit=5)

        # Stage 1: Cohort Builder
        build_result = build_cohorts(customers=customers, orders=orders, cohort_type=cohort_type)
        if build_result.get("status") == "error":
            return self._fail(f"Cohort building failed: {build_result.get('error', 'unknown')}", time.monotonic() - start)
        cohorts = build_result.get("cohorts", [])

        # Stage 2: Retention Calculator
        ret_result = calculate_retention(cohorts=cohorts, orders=orders, cohort_type=cohort_type)
        if ret_result.get("status") == "error":
            return self._fail(f"Retention calculation failed: {ret_result.get('error', 'unknown')}", time.monotonic() - start)
        cohort_retention = ret_result.get("cohort_retention", [])
        retention_matrix = ret_result.get("retention_matrix", [])

        # Stage 3: Revenue Tracker
        rev_result = track_revenue(cohorts=cohorts, orders=orders)
        if rev_result.get("status") == "error":
            return self._fail(f"Revenue tracking failed: {rev_result.get('error', 'unknown')}", time.monotonic() - start)
        cohort_revenues = rev_result.get("cohort_revenues", [])

        # Stage 4: LTV Projector
        ltv_result = project_ltv(cohort_retention=cohort_retention, cohort_revenues=cohort_revenues)
        if ltv_result.get("status") == "error":
            return self._fail(f"LTV projection failed: {ltv_result.get('error', 'unknown')}", time.monotonic() - start)
        projections = ltv_result.get("projections", [])
        best_cohort = ltv_result.get("best_cohort", "")
        trends = ltv_result.get("trends", {})

        # Stage 5: Memory Writer (non-fatal)
        _write_result = write_cohort_result(
            cohorts=projections, retention_matrix=retention_matrix,
            best_cohort=best_cohort, trends=trends,
        )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "cohorts": projections,
                "retention_matrix": retention_matrix,
                "best_cohort": best_cohort,
                "trends": trends,
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
