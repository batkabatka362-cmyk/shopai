"""Trend Detection Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Signal Collector → Momentum Calculator → Peak Detector →
  Forecast Builder → Memory Writer → Output

Engine contract:
  Input:  {status, data: {data_points, categories}, meta, error}
  Output: {status, data: {trends: [{name, direction, momentum, confidence}]}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .signal_collector import collect_signals
from .momentum_calculator import calculate_momentum
from .peak_detector import detect_peaks
from .forecast_builder import build_forecasts
from .memory_reader import read_past_trends
from .memory_writer import write_trend_result


class TrendDetectionEngine:
    """Trend Detection Engine — orchestrator only, no logic."""

    ENGINE_NAME = "trend_detection"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full trend detection pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            TrendOutput dict.
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

        data_points = data.get("data_points", [])
        categories = data.get("categories", [])

        if not data_points:
            return self._fail("Data points list is required", 0.0)

        # ---- Stage 1: Read past trends (non-blocking) ----
        _past = read_past_trends(limit=5)

        # ---- Stage 2: Signal Collector ----
        signal_result = collect_signals(
            data_points=data_points,
            categories=categories,
        )
        if signal_result.get("status") == "error":
            return self._fail(
                f"Signal collection failed: {signal_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        signals = signal_result.get("signals", [])

        # ---- Stage 3: Momentum Calculator ----
        momentum_result = calculate_momentum(
            data_points=data_points,
            signals=signals,
        )
        if momentum_result.get("status") == "error":
            return self._fail(
                f"Momentum calculation failed: {momentum_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        momentums = momentum_result.get("momentums", [])

        # ---- Stage 4: Peak Detector ----
        peak_result = detect_peaks(
            data_points=data_points,
            signals=signals,
        )
        if peak_result.get("status") == "error":
            return self._fail(
                f"Peak detection failed: {peak_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        _peaks = peak_result.get("peaks", [])

        # ---- Stage 5: Forecast Builder ----
        forecast_result = build_forecasts(
            data_points=data_points,
            signals=signals,
            momentums=momentums,
        )
        if forecast_result.get("status") == "error":
            return self._fail(
                f"Forecast building failed: {forecast_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        forecasts = forecast_result.get("forecasts", [])

        # ---- Stage 6: Assemble trend output ----
        mom_map = {str(m.get("name", "")): m for m in momentums}
        fc_map = {str(f.get("name", "")): f for f in forecasts}

        trends: list[dict[str, Any]] = []
        for signal in signals:
            name = str(signal.get("name", "unknown"))
            mom = mom_map.get(name, {})
            fc = fc_map.get(name, {})

            trends.append({
                "name": name,
                "direction": mom.get("direction", "flat"),
                "momentum": mom.get("momentum", 0.0),
                "confidence": fc.get("confidence", 0.0),
                "forecast_next": fc.get("forecast_next_period", 0.0),
            })

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_trend_result(trends=trends)

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "trends": trends,
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
