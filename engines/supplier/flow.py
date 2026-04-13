"""Supplier Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Performance Scorer → Risk Assessor → Negotiation Advisor → Relationship Tracker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {suppliers, orders, quality_data}, meta, error}
  Output: {status, data: {scores, negotiation_tips, relationship_health}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .performance_scorer import score_performance
from .risk_assessor import assess_risk
from .negotiation_advisor import advise_negotiation
from .relationship_tracker import track_relationships
from .memory_reader import read_past_results
from .memory_writer import write_result


class SupplierEngine:
    """Supplier Engine — orchestrator only, no logic."""

    ENGINE_NAME = "supplier"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full supplier pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            SupplierOutput dict.
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

        suppliers = data.get("suppliers", [])
        orders = data.get("orders", [])
        quality_data = data.get("quality_data", [])

        if not suppliers:
            return self._fail("Suppliers list is required", 0.0)

        # ---- Stage 1: Read past results (non-blocking) ----
        _past = read_past_results(limit=5)

        # ---- Stage 2: Score supplier performance: quality, delivery, cost ----
        performance_scorer_result = score_performance(
            suppliers=suppliers, orders=orders, quality_data=quality_data,
        )
        if performance_scorer_result.get("status") == "error":
            return self._fail(
                f"Score supplier performance: quality, delivery, cost failed: {performance_scorer_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        performance_scorer_data = performance_scorer_result.get("result", {})

        # ---- Stage 3: Assess supplier risk ----
        risk_assessor_result = assess_risk(
            suppliers=suppliers, orders=orders, quality_data=quality_data, performance_scorer_data=performance_scorer_data,
        )
        if risk_assessor_result.get("status") == "error":
            return self._fail(
                f"Assess supplier risk failed: {risk_assessor_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        risk_assessor_data = risk_assessor_result.get("result", {})

        # ---- Stage 4: Advise on negotiations ----
        negotiation_advisor_result = advise_negotiation(
            suppliers=suppliers, orders=orders, quality_data=quality_data, performance_scorer_data=performance_scorer_data, risk_assessor_data=risk_assessor_data,
        )
        if negotiation_advisor_result.get("status") == "error":
            return self._fail(
                f"Advise on negotiations failed: {negotiation_advisor_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        negotiation_advisor_data = negotiation_advisor_result.get("result", {})

        # ---- Stage 5: Track relationship health ----
        relationship_tracker_result = track_relationships(
            suppliers=suppliers, orders=orders, quality_data=quality_data, performance_scorer_data=performance_scorer_data, risk_assessor_data=risk_assessor_data, negotiation_advisor_data=negotiation_advisor_data,
        )
        if relationship_tracker_result.get("status") == "error":
            return self._fail(
                f"Track relationship health failed: {relationship_tracker_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        relationship_tracker_data = relationship_tracker_result.get("result", {})

        # ---- Memory Writer (non-fatal) ----
        output_data = {
                "scores": relationship_tracker_data.get("scores", []),
                "negotiation_tips": relationship_tracker_data.get("negotiation_tips", []),
                "relationship_health": relationship_tracker_data.get("relationship_health", {}),
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
