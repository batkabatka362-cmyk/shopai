"""Competitor Monitor Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Competitor Data → Price Watcher → Product Scanner → Alert Generator →
  Strategy Advisor → Memory Writer → Output

PURPOSE: Real-time competitor price and product monitoring.

Engine contract:
  Input:  {status, data: {competitors: [{name, url, products}], our_products, alert_thresholds}, meta, error}
  Output: {status, data: {price_changes, new_products, alerts, recommended_responses}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .price_watcher import watch_prices
from .product_scanner import scan_products
from .alert_generator import generate_alerts
from .strategy_advisor import advise_strategy
from .memory_reader import read_past_monitoring
from .memory_writer import write_monitoring_result


class CompetitorMonitorEngine:
    """Competitor Monitor Engine — orchestrator only, no logic."""

    ENGINE_NAME = "competitor_monitor"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full competitor monitoring pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            CompetitorMonitorOutput dict.
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

        competitors = data.get("competitors", [])
        our_products = data.get("our_products", [])
        alert_thresholds = data.get("alert_thresholds", {})

        if not competitors:
            return self._fail("Competitor list is required", 0.0)

        # ---- Stage 1: Read past monitoring data (non-blocking) ----
        _past = read_past_monitoring(limit=5)

        # ---- Stage 2: Price Watcher ----
        price_result = watch_prices(
            competitors=competitors,
            our_products=our_products,
        )
        if price_result.get("status") == "error":
            return self._fail(
                f"Price watching failed: {price_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        price_changes = price_result.get("price_changes", [])

        # ---- Stage 3: Product Scanner ----
        scan_result = scan_products(
            competitors=competitors,
            our_products=our_products,
        )
        if scan_result.get("status") == "error":
            return self._fail(
                f"Product scanning failed: {scan_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        new_products = scan_result.get("new_products", [])

        # ---- Stage 4: Alert Generator ----
        alert_result = generate_alerts(
            price_changes=price_changes,
            new_products=new_products,
            alert_thresholds=alert_thresholds,
        )
        if alert_result.get("status") == "error":
            return self._fail(
                f"Alert generation failed: {alert_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        alerts = alert_result.get("alerts", [])

        # ---- Stage 5: Strategy Advisor ----
        strategy_result = advise_strategy(
            price_changes=price_changes,
            new_products=new_products,
            alerts=alerts,
            our_products=our_products,
        )
        if strategy_result.get("status") == "error":
            return self._fail(
                f"Strategy advising failed: {strategy_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        recommended_responses = strategy_result.get("responses", [])

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_monitoring_result(
            price_changes=price_changes,
            new_products=new_products,
            alerts=alerts,
            recommended_responses=recommended_responses,
        )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "price_changes": price_changes,
                "new_products": new_products,
                "alerts": alerts,
                "recommended_responses": recommended_responses,
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
