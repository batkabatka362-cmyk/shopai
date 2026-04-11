"""Report Dashboard Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Memory Reader → Data Aggregator → Metric Calculator →
  Chart Builder → Summary Writer → Memory Writer → Output

Engine contract:
  Input:  {status, data: {period, data_sources, format}, meta, error}
  Output: {status, data: {dashboard, period_comparison, highlights, action_items}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .data_aggregator import aggregate_data
from .metric_calculator import calculate_metrics
from .chart_builder import build_charts
from .summary_writer import write_summary
from .memory_reader import read_past_dashboards
from .memory_writer import write_dashboard_result


class ReportDashboardEngine:
    """Report Dashboard Engine — orchestrator only, no logic."""

    ENGINE_NAME = "report_dashboard"

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

        period = str(data.get("period", "last_30_days"))
        data_sources = data.get("data_sources", ["orders", "products", "customers", "marketing"])
        report_format = str(data.get("format", "full"))

        if not data_sources:
            return self._fail("At least one data source is required", 0.0)

        # ---- Stage 1: Memory Reader ----
        _past = read_past_dashboards(limit=5)

        # ---- Stage 2: Data Aggregator ----
        agg_result = aggregate_data(data_sources=data_sources, period=period, raw_data=data.get("raw_data"))
        if agg_result.get("status") == "error":
            return self._fail(f"Data aggregation failed: {agg_result.get('error', 'unknown')}", time.monotonic() - start)
        aggregated = agg_result.get("aggregated", [])

        # ---- Stage 3: Metric Calculator ----
        metric_result = calculate_metrics(aggregated_data=aggregated)
        if metric_result.get("status") == "error":
            return self._fail(f"Metric calculation failed: {metric_result.get('error', 'unknown')}", time.monotonic() - start)
        metrics = metric_result.get("metrics", [])

        # ---- Stage 4: Chart Builder ----
        chart_result = build_charts(metrics=metrics, aggregated_data=aggregated)
        if chart_result.get("status") == "error":
            return self._fail(f"Chart building failed: {chart_result.get('error', 'unknown')}", time.monotonic() - start)
        charts = chart_result.get("charts", [])

        # ---- Stage 5: Summary Writer ----
        summary_result = write_summary(metrics=metrics, period=period)
        if summary_result.get("status") == "error":
            return self._fail(f"Summary writing failed: {summary_result.get('error', 'unknown')}", time.monotonic() - start)
        summary = summary_result.get("summary", "")
        highlights = summary_result.get("highlights", [])
        action_items = summary_result.get("action_items", [])
        period_comparison = summary_result.get("period_comparison", {})

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write = write_dashboard_result(metrics=metrics, highlights=highlights, action_items=action_items)

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "dashboard": {"metrics": metrics, "charts": charts, "summary": summary},
                "period_comparison": period_comparison,
                "highlights": highlights,
                "action_items": action_items,
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
