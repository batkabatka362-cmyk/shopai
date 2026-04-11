"""Performance Monitor Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Page/Timing Data -> Speed Analyzer -> Uptime Tracker ->
  Bottleneck Finder -> Alert Manager -> Output

Engine contract:
  Input:  {status, data: {pages, load_times, uptime_data, thresholds}, meta, error}
  Output: {status, data: {performance_scores, bottlenecks, uptime_pct, alerts, recommendations}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .speed_analyzer import analyze_speed
from .uptime_tracker import track_uptime
from .bottleneck_finder import find_bottlenecks
from .alert_manager import manage_alerts


class PerformanceMonitorEngine:
    """Performance Monitor Engine — orchestrator only, no logic."""

    ENGINE_NAME = "performance_monitor"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full performance monitoring pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            Performance monitoring output dict.
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

        pages = data.get("pages", [])
        load_times = data.get("load_times", [])
        uptime_data = data.get("uptime_data", [])
        thresholds = data.get("thresholds", {})

        if not pages and not uptime_data:
            return self._fail("Pages or uptime_data is required", 0.0)

        # ---- Stage 1: Speed Analyzer ----
        speed_result = analyze_speed(pages=pages, load_times=load_times)
        if speed_result.get("status") == "error":
            return self._fail(
                f"Speed analysis failed: {speed_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        performance_scores = speed_result.get("performance_scores", [])

        # ---- Stage 2: Uptime Tracker ----
        uptime_result = track_uptime(uptime_data=uptime_data)
        if uptime_result.get("status") == "error":
            return self._fail(
                f"Uptime tracking failed: {uptime_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        uptime_pct = float(uptime_result.get("uptime_pct", 100.0))
        downtime_windows = uptime_result.get("downtime_windows", [])

        # ---- Stage 3: Bottleneck Finder ----
        bottleneck_result = find_bottlenecks(
            performance_scores=performance_scores,
            uptime_pct=uptime_pct,
            downtime_windows=downtime_windows,
        )
        if bottleneck_result.get("status") == "error":
            return self._fail(
                f"Bottleneck finding failed: {bottleneck_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        bottlenecks = bottleneck_result.get("bottlenecks", [])

        # ---- Stage 4: Alert Manager ----
        alert_result = manage_alerts(
            performance_scores=performance_scores,
            bottlenecks=bottlenecks,
            uptime_pct=uptime_pct,
            thresholds=thresholds,
        )
        if alert_result.get("status") == "error":
            return self._fail(
                f"Alert management failed: {alert_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        alerts = alert_result.get("alerts", [])
        recommendations = alert_result.get("recommendations", [])

        # ---- Stage 5: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "performance_scores": performance_scores,
                "bottlenecks": bottlenecks,
                "uptime_pct": uptime_pct,
                "alerts": alerts,
                "recommendations": recommendations,
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
