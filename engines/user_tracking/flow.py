"""User Tracking Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Memory Reader → Session Builder → Journey Mapper →
  Touchpoint Analyzer → Attribution Tracker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {events, users, sessions}, meta, error}
  Output: {status, data: {journeys, touchpoints, attribution, session_stats}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .session_builder import build_sessions
from .journey_mapper import map_journeys
from .touchpoint_analyzer import analyze_touchpoints
from .attribution_tracker import track_attribution
from .memory_reader import read_past_tracking
from .memory_writer import write_tracking_result


class UserTrackingEngine:
    """User Tracking Engine — orchestrator only, no logic."""

    ENGINE_NAME = "user_tracking"

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

        events = data.get("events", [])
        users = data.get("users", [])
        sessions = data.get("sessions", [])

        if not events and not sessions:
            return self._fail("Either events or sessions is required", 0.0)

        _past = read_past_tracking(limit=5)

        # ---- Session Builder ----
        session_result = build_sessions(events=events, users=users)
        if session_result.get("status") == "error":
            return self._fail(f"Session building failed: {session_result.get('error', 'unknown')}", time.monotonic() - start)
        built_sessions = session_result.get("sessions", [])

        # ---- Journey Mapper ----
        journey_result = map_journeys(sessions=built_sessions)
        if journey_result.get("status") == "error":
            return self._fail(f"Journey mapping failed: {journey_result.get('error', 'unknown')}", time.monotonic() - start)
        journeys = journey_result.get("journeys", [])

        # ---- Touchpoint Analyzer ----
        tp_result = analyze_touchpoints(journeys=journeys)
        if tp_result.get("status") == "error":
            return self._fail(f"Touchpoint analysis failed: {tp_result.get('error', 'unknown')}", time.monotonic() - start)
        touchpoints = tp_result.get("touchpoints", [])

        # ---- Attribution Tracker ----
        attr_result = track_attribution(journeys=journeys)
        if attr_result.get("status") == "error":
            return self._fail(f"Attribution tracking failed: {attr_result.get('error', 'unknown')}", time.monotonic() - start)
        attribution = attr_result.get("attribution", [])

        session_stats: dict[str, Any] = {
            "total_sessions": session_result.get("total_sessions", 0),
            "unique_users": session_result.get("unique_users", 0),
            "total_journeys": journey_result.get("total_journeys", 0),
            "conversion_rate_pct": journey_result.get("conversion_rate_pct", 0.0),
        }

        _write_result = write_tracking_result(
            journeys=journeys, touchpoints=touchpoints,
            attribution=attribution, session_stats=session_stats,
        )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "journeys": journeys,
                "touchpoints": touchpoints,
                "attribution": attribution,
                "session_stats": session_stats,
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
