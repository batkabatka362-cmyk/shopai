"""Event Tracking Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Memory Reader → Event Collector → Event Categorizer →
  Metric Aggregator → Anomaly Detector → Memory Writer → Output

Engine contract:
  Input:  {status, data: {events, period}, meta, error}
  Output: {status, data: {event_summary, metrics, anomalies, trends}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .event_collector import collect_events
from .event_categorizer import categorize_events
from .metric_aggregator import aggregate_metrics
from .anomaly_detector import detect_anomalies
from .memory_reader import read_past_events
from .memory_writer import write_event_result


class EventTrackingEngine:
    """Event Tracking Engine — orchestrator only, no logic."""

    ENGINE_NAME = "event_tracking"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

        # ---- Stage 0: Input validation ----
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
        period = str(data.get("period", "day"))

        if not events:
            return self._fail("Events list is required", 0.0)

        # ---- Stage 1: Read past events (non-blocking) ----
        _past = read_past_events(limit=5)

        # ---- Stage 2: Event Collector ----
        collect_result = collect_events(events=events)
        if collect_result.get("status") == "error":
            return self._fail(
                f"Event collection failed: {collect_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        event_groups = collect_result.get("groups", [])

        # ---- Stage 3: Event Categorizer ----
        categorize_result = categorize_events(event_groups=event_groups)
        if categorize_result.get("status") == "error":
            return self._fail(
                f"Event categorization failed: {categorize_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        categorized = categorize_result.get("categorized", [])

        # ---- Stage 4: Metric Aggregator ----
        metric_result = aggregate_metrics(
            event_groups=event_groups,
            categorized=categorized,
            period=period,
        )
        if metric_result.get("status") == "error":
            return self._fail(
                f"Metric aggregation failed: {metric_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        metrics = metric_result.get("metrics", [])

        # ---- Stage 5: Anomaly Detector ----
        anomaly_result = detect_anomalies(
            event_groups=event_groups,
            categorized=categorized,
        )
        if anomaly_result.get("status") == "error":
            return self._fail(
                f"Anomaly detection failed: {anomaly_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        anomalies = anomaly_result.get("anomalies", [])

        # ---- Stage 6: Build event summary and trends ----
        event_summary: dict[str, Any] = {
            "total_events": collect_result.get("total_events", 0),
            "unique_types": collect_result.get("unique_types", 0),
            "category_counts": categorize_result.get("category_counts", {}),
            "period": period,
        }

        trends: list[dict[str, Any]] = []
        for cat_event in categorized:
            trends.append({
                "event_type": cat_event.get("event_type", ""),
                "category": cat_event.get("category", ""),
                "count": cat_event.get("count", 0),
                "direction": "stable",
            })

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_event_result(
            event_summary=event_summary,
            metrics=metrics,
            anomalies=anomalies,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "event_summary": event_summary,
                "metrics": metrics,
                "anomalies": anomalies,
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
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
