"""CustomerSupport Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Ticket Classifier → Resolution Finder → Workload Analyzer → Satisfaction Tracker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {tickets, resolutions, agents}, meta, error}
  Output: {status, data: {classified_tickets, suggested_resolutions, workload_report, satisfaction_scores}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .ticket_classifier import classify_tickets
from .resolution_finder import find_resolutions
from .ticket_tag_applier import apply_ticket_tags
from .workload_analyzer import analyze_workload
from .satisfaction_tracker import track_satisfaction
from .memory_reader import read_past_results
from .memory_writer import write_result


class CustomerSupportEngine:
    """CustomerSupport Engine — orchestrator only, no logic."""

    ENGINE_NAME = "customer_support"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full customer support pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            CustomerSupportOutput dict.
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

        tickets = data.get("tickets", [])
        resolutions = data.get("resolutions", [])
        agents = data.get("agents", [])

        if not tickets:
            return self._fail("Tickets list is required", 0.0)

        # ---- Stage 1: Read past results (non-blocking) ----
        _past = read_past_results(limit=5)

        # ---- Stage 2: Classify support tickets ----
        ticket_classifier_result = classify_tickets(
            tickets=tickets, resolutions=resolutions, agents=agents,
        )
        if ticket_classifier_result.get("status") == "error":
            return self._fail(
                f"Classify support tickets failed: {ticket_classifier_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        ticket_classifier_data = ticket_classifier_result.get("result", {})

        # ---- Stage 3: Find resolution from knowledge base ----
        resolution_finder_result = find_resolutions(
            tickets=tickets, resolutions=resolutions, agents=agents, ticket_classifier_data=ticket_classifier_data,
        )
        if resolution_finder_result.get("status") == "error":
            return self._fail(
                f"Find resolution from knowledge base failed: {resolution_finder_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        resolution_finder_data = resolution_finder_result.get("result", {})

        # ---- Stage 4: Analyze support team workload ----
        workload_analyzer_result = analyze_workload(
            tickets=tickets, resolutions=resolutions, agents=agents, ticket_classifier_data=ticket_classifier_data, resolution_finder_data=resolution_finder_data,
        )
        if workload_analyzer_result.get("status") == "error":
            return self._fail(
                f"Analyze support team workload failed: {workload_analyzer_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        workload_analyzer_data = workload_analyzer_result.get("result", {})

        # ---- Stage 5: Track customer satisfaction ----
        satisfaction_tracker_result = track_satisfaction(
            tickets=tickets, resolutions=resolutions, agents=agents, ticket_classifier_data=ticket_classifier_data, resolution_finder_data=resolution_finder_data, workload_analyzer_data=workload_analyzer_data,
        )
        if satisfaction_tracker_result.get("status") == "error":
            return self._fail(
                f"Track customer satisfaction failed: {satisfaction_tracker_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        satisfaction_tracker_data = satisfaction_tracker_result.get("result", {})

        # ---- Memory Writer (non-fatal) ----
        output_data = {
                "classified_tickets": satisfaction_tracker_data.get("classified_tickets", []),
                "suggested_resolutions": satisfaction_tracker_data.get("suggested_resolutions", []),
                "workload_report": satisfaction_tracker_data.get("workload_report", {}),
                "satisfaction_scores": satisfaction_tracker_data.get("satisfaction_scores", {}),
        }
        _write_result = write_result(output_data=output_data)

        # ---- Wave 104: ticket-tag applier (opt-in) ----
        # data.apply_ticket_tags=True -> push priority /
        # sentiment / category tags to the addressable
        # customer via SHOPIFY_TAG_CUSTOMER. Default OFF;
        # advisory behaviour preserved for existing callers.
        tag_apply_results: list[dict[str, Any]] = []
        if data.get("apply_ticket_tags") is True:
            tag_apply_results = apply_ticket_tags(
                classified_tickets=output_data[
                    "classified_tickets"
                ],
                raw_tickets=tickets,
            )
        output_data["tag_apply_results"] = tag_apply_results

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
