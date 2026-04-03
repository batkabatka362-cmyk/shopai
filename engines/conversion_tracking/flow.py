"""Conversion Tracking Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input Data -> Event Tracker -> Attribution Modeler -> Funnel Analyzer ->
  Goal Tracker -> Memory Writer -> Output

Engine contract:
  Input:  {status, data: {events, touchpoints, goals, attribution_model}, meta, error}
  Output: {status, data: {conversions, funnel, goal_progress, attribution_report}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .event_tracker import track_events
from .attribution_modeler import model_attribution
from .funnel_analyzer import analyze_funnel
from .goal_tracker import track_goals
from .memory_reader import read_past_conversions
from .memory_writer import write_conversion_result


class ConversionTrackingEngine:
    """Conversion Tracking Engine — orchestrator only, no logic."""

    ENGINE_NAME = "conversion_tracking"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full conversion tracking pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ConversionTrackingOutput dict.
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

        events = data.get("events", [])
        touchpoints = data.get("touchpoints", [])
        goals = data.get("goals", [])
        attribution_model = str(data.get("attribution_model", "last_touch"))

        if not events:
            return self._fail("Events list is required", 0.0)

        # ---- Stage 1: Read past conversions (non-blocking) ----
        _past = read_past_conversions(limit=5)

        # ---- Stage 2: Event Tracker ----
        event_result = track_events(events=events)
        if event_result.get("status") == "error":
            return self._fail(
                f"Event tracking failed: {event_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        tracked_events = event_result.get("tracked_events", [])

        # ---- Stage 3: Attribution Modeler ----
        attribution_result = model_attribution(
            tracked_events=tracked_events,
            touchpoints=touchpoints,
            model=attribution_model,
        )
        if attribution_result.get("status") == "error":
            return self._fail(
                f"Attribution modeling failed: {attribution_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        attributed_conversions = attribution_result.get("attributed_conversions", [])
        attribution_report = attribution_result.get("attribution_report", {})

        # ---- Stage 4: Funnel Analyzer ----
        funnel_result = analyze_funnel(
            tracked_events=tracked_events,
            touchpoints=touchpoints,
        )
        if funnel_result.get("status") == "error":
            return self._fail(
                f"Funnel analysis failed: {funnel_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        funnel = funnel_result.get("funnel", {})

        # ---- Stage 5: Goal Tracker ----
        goal_result = track_goals(
            tracked_events=tracked_events,
            goals=goals,
        )
        if goal_result.get("status") == "error":
            return self._fail(
                f"Goal tracking failed: {goal_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        goal_progress = goal_result.get("goal_progress", [])

        # ---- Stage 6: Assemble conversions output ----
        conversions: list[dict[str, Any]] = []
        for ac in attributed_conversions:
            conversions.append({
                "event": str(ac.get("event_type", ac.get("event_id", ""))),
                "value": float(ac.get("value", 0.0)),
                "source": str(ac.get("source", "")),
                "attribution": ac.get("attribution", {}),
            })

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_conversion_result(
            conversions=conversions,
            funnel=funnel,
            goal_progress=goal_progress,
            attribution_report=attribution_report,
        )

        # ---- Stage 8: Return output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "conversions": conversions,
                "funnel": funnel,
                "goal_progress": goal_progress,
                "attribution_report": attribution_report,
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
