"""Forecasting Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Historical Data -> Data Preprocessor -> Trend Analyzer ->
  Seasonality Detector -> Moving Average Calculator -> Regression Modeler ->
  Forecast Generator -> Confidence Estimator -> Scenario Builder ->
  Memory Writer -> Output

Engine contract:
  Input:  {status, data: {metric: "daily_revenue",
           history: [{date: "2026-01-01", value: 500}, ...],
           forecast_periods: 30, granularity: "daily"},
           meta, error}
  Output: {status, data: {forecast: [{date, predicted, lower_80, upper_80,
           lower_95, upper_95}], trend: {direction, strength, slope},
           seasonality: {detected, period, amplitude},
           scenarios: {optimistic: [...], baseline: [...], pessimistic: [...]},
           model_accuracy: {mae, rmse, mape, r_squared}, confidence: 0.0},
           meta: {engine: "forecasting"}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .data_preprocessor import preprocess
from .trend_analyzer import analyze_trend
from .seasonality_detector import detect_seasonality
from .moving_average_calculator import compute_moving_averages
from .regression_modeler import build_regression
from .forecast_generator import generate_forecast
from .confidence_estimator import estimate_confidence
from .scenario_builder import build_scenarios
from .memory_reader import read_recent_forecasts
from .memory_writer import write_forecast


class ForecastingEngine:
    """Forecasting Engine — orchestrator only, no logic."""

    ENGINE_NAME = "forecasting"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full forecasting pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ForecastingOutput dict.
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

        history = data.get("history", [])
        if not isinstance(history, list) or not history:
            return self._fail("At least one history point is required", 0.0)

        metric = str(data.get("metric", "unknown"))
        forecast_periods = int(data.get("forecast_periods", 30))
        granularity = str(data.get("granularity", "daily"))

        # ---- Stage 0.5: Memory read (non-fatal) ----
        _past = read_recent_forecasts(metric=metric, hours=168.0)

        # ---- Stage 1: Data Preprocessor ----
        preprocess_result = preprocess(history=history, granularity=granularity)
        if preprocess_result.get("status") == "error":
            return self._fail(
                preprocess_result.get("error", "Preprocessing failed"), start,
            )
        cleaned_data = preprocess_result.get("cleaned", [])
        if not cleaned_data:
            return self._fail("Preprocessing produced no cleaned data", start)

        # ---- Stage 2: Trend Analyzer (Mistral) ----
        trend_result = analyze_trend(cleaned_data=cleaned_data)
        if trend_result.get("status") == "error":
            return self._fail(
                trend_result.get("error", "Trend analysis failed"), start,
            )
        trend = trend_result.get("trend", {})

        # ---- Stage 3: Seasonality Detector ----
        season_result = detect_seasonality(
            cleaned_data=cleaned_data, granularity=granularity,
        )
        if season_result.get("status") == "error":
            return self._fail(
                season_result.get("error", "Seasonality detection failed"), start,
            )
        seasonality = season_result.get("seasonality", {})

        # ---- Stage 4: Moving Average Calculator ----
        ma_result = compute_moving_averages(cleaned_data=cleaned_data)
        if ma_result.get("status") == "error":
            return self._fail(
                ma_result.get("error", "Moving average calculation failed"), start,
            )
        moving_averages = ma_result.get("moving_averages", {})

        # ---- Stage 5: Regression Modeler (Mistral) ----
        reg_result = build_regression(cleaned_data=cleaned_data)
        if reg_result.get("status") == "error":
            return self._fail(
                reg_result.get("error", "Regression modeling failed"), start,
            )
        regression = reg_result.get("regression", {})

        # ---- Stage 6: Forecast Generator ----
        fc_result = generate_forecast(
            cleaned_data=cleaned_data,
            trend=trend,
            seasonality=seasonality,
            regression=regression,
            moving_averages=moving_averages,
            forecast_periods=forecast_periods,
            granularity=granularity,
        )
        if fc_result.get("status") == "error":
            return self._fail(
                fc_result.get("error", "Forecast generation failed"), start,
            )
        raw_forecast = fc_result.get("forecast", [])
        residuals = fc_result.get("residuals", [])

        # ---- Stage 7: Confidence Estimator ----
        ci_result = estimate_confidence(
            forecast=raw_forecast,
            residuals=residuals,
            cleaned_data=cleaned_data,
        )
        if ci_result.get("status") == "error":
            return self._fail(
                ci_result.get("error", "Confidence estimation failed"), start,
            )
        forecast_with_ci = ci_result.get("forecast_with_ci", [])
        model_accuracy = ci_result.get("model_accuracy", {})
        overall_confidence = ci_result.get("overall_confidence", 0.0)

        # ---- Stage 8: Scenario Builder (LLaMA) ----
        sc_result = build_scenarios(
            forecast_with_ci=forecast_with_ci,
            trend=trend,
            model_accuracy=model_accuracy,
        )
        if sc_result.get("status") == "error":
            return self._fail(
                sc_result.get("error", "Scenario building failed"), start,
            )
        scenarios = sc_result.get("scenarios", {})

        # ---- Stage 9: Memory Writer (non-fatal) ----
        _write = write_forecast(
            metric=metric,
            forecast_periods=forecast_periods,
            granularity=granularity,
            model_accuracy=model_accuracy,
            overall_confidence=overall_confidence,
            trend_direction=trend.get("direction", "unknown"),
            seasonality_detected=seasonality.get("detected", False),
            forecast_count=len(forecast_with_ci),
        )

        # ---- Build final output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "forecast": forecast_with_ci,
                "trend": {
                    "direction": trend.get("direction", "unknown"),
                    "strength": trend.get("strength", 0.0),
                    "slope": trend.get("slope", 0.0),
                },
                "seasonality": {
                    "detected": seasonality.get("detected", False),
                    "period": seasonality.get("period", 0),
                    "amplitude": seasonality.get("amplitude", 0.0),
                },
                "scenarios": scenarios,
                "model_accuracy": model_accuracy,
                "confidence": overall_confidence,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
                "metric": metric,
                "history_points": len(cleaned_data),
                "forecast_periods": forecast_periods,
                "granularity": granularity,
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        if isinstance(elapsed, float) and elapsed > 1e6:
            # elapsed is actually a start time — compute real elapsed
            elapsed = time.monotonic() - elapsed
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(max(elapsed, 0.0), 3),
            },
            "error": reason,
        }
