"""LTV:CAC Dashboard Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → LTV Calculator → CAC Calculator → Ratio Tracker →
  Alert Manager → Memory Writer → Output

Engine contract:
  Input:  {status, data: {customers, orders, marketing_spend, channels}, meta, error}
  Output: {status, data: {ltv, cac, ratio, trend, alerts, payback_months}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .ltv_calculator import calculate_ltv
from .cac_calculator import calculate_cac
from .ratio_tracker import track_ratio
from .alert_manager import manage_alerts
from .memory_reader import read_past_ltv_cac
from .memory_writer import write_ltv_cac_result


class LtvCacDashboardEngine:
    """LTV:CAC Dashboard Engine — orchestrator only, no logic."""

    ENGINE_NAME = "ltv_cac_dashboard"

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

        customers = data.get("customers", [])
        orders = data.get("orders", [])
        marketing_spend = data.get("marketing_spend", [])
        channels = data.get("channels", [])

        if not customers and not orders:
            return self._fail("Customers or orders list is required", 0.0)

        _past = read_past_ltv_cac(limit=5)

        # Stage 1: LTV Calculator
        ltv_result = calculate_ltv(customers=customers, orders=orders)
        if ltv_result.get("status") == "error":
            return self._fail(f"LTV calculation failed: {ltv_result.get('error', 'unknown')}", time.monotonic() - start)
        ltv = ltv_result.get("ltv", {})

        # Stage 2: CAC Calculator
        cac_result = calculate_cac(marketing_spend=marketing_spend, customers=customers, channels=channels)
        if cac_result.get("status") == "error":
            return self._fail(f"CAC calculation failed: {cac_result.get('error', 'unknown')}", time.monotonic() - start)
        cac = cac_result.get("cac", {})

        # Stage 3: Ratio Tracker
        ratio_result = track_ratio(ltv=ltv, cac=cac)
        if ratio_result.get("status") == "error":
            return self._fail(f"Ratio tracking failed: {ratio_result.get('error', 'unknown')}", time.monotonic() - start)
        ratio = ratio_result.get("ratio", 0.0)
        trend = ratio_result.get("trend", "unknown")
        payback_months = ratio_result.get("payback_months", 0.0)

        # Stage 4: Alert Manager
        alert_result = manage_alerts(ratio=ratio, trend=trend, cac=cac, ltv=ltv)
        if alert_result.get("status") == "error":
            return self._fail(f"Alert management failed: {alert_result.get('error', 'unknown')}", time.monotonic() - start)
        alerts = alert_result.get("alerts", [])

        # Stage 5: Memory Writer (non-fatal)
        _write_result = write_ltv_cac_result(
            ltv=ltv, cac=cac, ratio=ratio, trend=trend,
            alerts=alerts, payback_months=payback_months,
        )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "ltv": ltv,
                "cac": cac,
                "ratio": ratio,
                "trend": trend,
                "alerts": alerts,
                "payback_months": payback_months,
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
