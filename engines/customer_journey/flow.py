"""Customer Journey Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Customer/Event Data -> Journey Builder -> Stage Analyzer ->
  Drop-off Detector -> Optimization Advisor -> Output

Engine contract:
  Input:  {status, data: {customers, events, touchpoints, conversions}, meta, error}
  Output: {status, data: {journey_map, stage_metrics, drop_off_points, optimizations}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .journey_builder import build_journey
from .stage_analyzer import analyze_stages
from .drop_off_detector import detect_drop_offs
from .optimization_advisor import advise_optimizations
from engines._shopify_hydrator import hydrate


class CustomerJourneyEngine:
    """Customer Journey Engine — orchestrator only, no logic."""

    ENGINE_NAME = "customer_journey"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full customer journey pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            Customer journey output dict.
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

        customers = data.get("customers", [])
        events = data.get("events", [])
        touchpoints = data.get("touchpoints", [])
        conversions = data.get("conversions", [])

        # Auto-hydrate customers from Shopify when caller left the
        # list empty. customers is auxiliary (events is gated),
        # but feeds the journey builder.
        customers = hydrate(
            supplied=customers if isinstance(customers, list) else [],
            capability_name="SHOPIFY_FETCH_CUSTOMERS",
            list_field="customers",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not events:
            return self._fail("Events list is required", 0.0)

        # ---- Stage 1: Journey Builder ----
        build_result = build_journey(
            customers=customers,
            events=events,
            touchpoints=touchpoints,
        )
        if build_result.get("status") == "error":
            return self._fail(
                f"Journey building failed: {build_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        journey_map = build_result.get("journey_map", {})
        customer_journeys = build_result.get("customer_journeys", [])

        # ---- Stage 2: Stage Analyzer ----
        stage_result = analyze_stages(
            journey_map=journey_map,
            customer_journeys=customer_journeys,
            conversions=conversions,
        )
        if stage_result.get("status") == "error":
            return self._fail(
                f"Stage analysis failed: {stage_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        stage_metrics = stage_result.get("stage_metrics", [])

        # ---- Stage 3: Drop-off Detector ----
        dropoff_result = detect_drop_offs(
            stage_metrics=stage_metrics,
            customer_journeys=customer_journeys,
        )
        if dropoff_result.get("status") == "error":
            return self._fail(
                f"Drop-off detection failed: {dropoff_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        drop_off_points = dropoff_result.get("drop_off_points", [])

        # ---- Stage 4: Optimization Advisor ----
        opt_result = advise_optimizations(
            drop_off_points=drop_off_points,
            stage_metrics=stage_metrics,
        )
        if opt_result.get("status") == "error":
            return self._fail(
                f"Optimization advising failed: {opt_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        optimizations = opt_result.get("optimizations", [])

        # ---- Stage 5: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "journey_map": journey_map,
                "stage_metrics": stage_metrics,
                "drop_off_points": drop_off_points,
                "optimizations": optimizations,
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
