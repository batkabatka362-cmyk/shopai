"""KPI Tracking Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input Data -> KPI Calculator -> Trend Analyzer -> Benchmark Comparator ->
  Alert Checker -> Memory Writer -> Output

Engine contract:
  Input:  {status, data: {orders, customers, costs, period, benchmarks}, meta, error}
  Output: {status, data: {kpis, trends, alerts, health_grade}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .kpi_calculator import calculate_kpis
from .trend_analyzer import analyze_trends
from .benchmark_comparator import compare_benchmarks
from .alert_checker import check_alerts
from .memory_reader import read_past_kpis
from .memory_writer import write_kpi_result


class KpiTrackingEngine:
    """KPI Tracking Engine — orchestrator only, no logic."""

    ENGINE_NAME = "kpi_tracking"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full KPI tracking pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            KpiTrackingOutput dict.
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

        orders = data.get("orders", [])
        customers = data.get("customers", [])
        costs = data.get("costs", [])
        period = str(data.get("period", "30d"))
        benchmarks = data.get("benchmarks", [])

        if not orders and not customers:
            return self._fail("Orders or customers data is required", 0.0)

        # ---- Stage 1: Read past KPIs (non-blocking) ----
        _past = read_past_kpis(limit=5)

        # ---- Stage 2: KPI Calculator ----
        kpi_result = calculate_kpis(
            orders=orders,
            customers=customers,
            costs=costs,
            period=period,
        )
        if kpi_result.get("status") == "error":
            return self._fail(
                f"KPI calculation failed: {kpi_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        kpis = kpi_result.get("kpis", {})

        # ---- Stage 3: Trend Analyzer ----
        past_records = _past.get("records", [])
        trend_result = analyze_trends(
            current_kpis=kpis,
            past_records=past_records,
        )
        if trend_result.get("status") == "error":
            return self._fail(
                f"Trend analysis failed: {trend_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        trends = trend_result.get("trends", [])

        # ---- Stage 4: Benchmark Comparator ----
        benchmark_result = compare_benchmarks(
            kpis=kpis,
            benchmarks=benchmarks,
        )
        if benchmark_result.get("status") == "error":
            return self._fail(
                f"Benchmark comparison failed: {benchmark_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        comparisons = benchmark_result.get("comparisons", [])

        # ---- Stage 5: Alert Checker ----
        alert_result = check_alerts(
            kpis=kpis,
            trends=trends,
            comparisons=comparisons,
        )
        if alert_result.get("status") == "error":
            return self._fail(
                f"Alert checking failed: {alert_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        alerts = alert_result.get("alerts", [])

        # ---- Stage 6: Compute health grade ----
        health_grade = _compute_health_grade(kpis, trends, alerts, comparisons)

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_kpi_result(
            kpis=kpis,
            trends=trends,
            alerts=alerts,
            health_grade=health_grade,
        )

        # ---- Stage 8: Return output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "kpis": kpis,
                "trends": trends,
                "alerts": alerts,
                "health_grade": health_grade,
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


def _compute_health_grade(
    kpis: dict[str, Any],
    trends: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
) -> str:
    """Compute an overall health grade (A-F) from KPI data."""
    score = 100.0

    # Penalize for critical alerts
    for alert in alerts:
        severity = str(alert.get("severity", ""))
        if severity == "critical":
            score -= 20
        elif severity == "warning":
            score -= 10
        elif severity == "info":
            score -= 2

    # Penalize for negative trends
    for trend in trends:
        direction = str(trend.get("direction", ""))
        change = abs(float(trend.get("change_pct", 0)))
        if direction == "down" and change > 10:
            score -= 10
        elif direction == "down" and change > 5:
            score -= 5

    # Reward for above-benchmark performance
    for comp in comparisons:
        percentile = str(comp.get("percentile", ""))
        if percentile == "above_average":
            score += 5
        elif percentile == "below_average":
            score -= 5

    score = max(0, min(100, score))

    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    else:
        return "F"
