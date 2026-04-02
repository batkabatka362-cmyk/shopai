"""A/B Testing Engine -- flow orchestrator.

This is the FLOW file.  It ONLY orchestrates -- no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Test Hypothesis -> Experiment Designer -> Sample Size Calculator ->
  Variant Builder -> Traffic Splitter -> Metric Collector ->
  Statistical Analyzer -> Winner Selector -> Risk Assessor ->
  Memory Writer -> Output

Engine contract:
  Input:  {status, data: {test_type, hypothesis, control, treatment,
           primary_metric, current_rate, mde, daily_traffic, ...}, meta, error}
  Output: {status, data: {experiment, sample_size, variants, traffic_split,
           metrics, analysis, winner, risk, confidence}, meta, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .experiment_designer import design_experiment
from .sample_size_calculator import calculate_sample_size
from .variant_builder import build_variants
from .traffic_splitter import split_traffic
from .metric_collector import collect_metrics
from .statistical_analyzer import analyze_statistics
from .winner_selector import select_winner
from .risk_assessor import assess_risk
from .memory_reader import read_past_tests, find_similar_past_run
from .memory_writer import write_test_result


class ABTestingEngine:
    """A/B Testing Engine -- orchestrator only, no logic."""

    ENGINE_NAME = "ab_testing"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full A/B testing pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ABTestOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation ----
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

        test_type = str(data.get("test_type", "pricing"))
        hypothesis = str(data.get("hypothesis", ""))
        control = data.get("control", {})
        treatment = data.get("treatment", {})
        primary_metric = str(data.get("primary_metric", "conversion_rate"))
        guardrail_metrics = list(data.get("guardrail_metrics", []))
        current_rate = float(data.get("current_rate", 0.0))
        mde = float(data.get("mde", 0.0))
        daily_traffic = int(data.get("daily_traffic", 0))
        alpha = float(data.get("alpha", 0.05))
        power = float(data.get("power", 0.80))
        segments = list(data.get("segments", []))
        history = list(data.get("history", []))

        if not hypothesis:
            return self._fail("Hypothesis is required", 0.0)
        if current_rate <= 0:
            return self._fail("current_rate must be positive", 0.0)
        if mde <= 0:
            return self._fail("mde must be positive", 0.0)
        if daily_traffic <= 0:
            return self._fail("daily_traffic must be positive", 0.0)

        # ---- Stage 1: Read past tests (non-blocking) ----
        _past = read_past_tests(test_type=test_type, limit=5)

        # ---- Stage 2: Experiment Designer (Mistral) ----
        exp_result = design_experiment(
            test_type=test_type,
            hypothesis=hypothesis,
            control=control,
            treatment=treatment,
            primary_metric=primary_metric,
            guardrail_metrics=guardrail_metrics,
            current_rate=current_rate,
            mde=mde,
        )
        if exp_result.get("status") == "error":
            return self._fail(
                f"Experiment design failed: {exp_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        experiment = exp_result.get("experiment", {})

        # ---- Stage 3: Sample Size Calculator ----
        ss_result = calculate_sample_size(
            primary_metric=primary_metric,
            current_rate=current_rate,
            mde=mde,
            alpha=alpha,
            power=power,
            daily_traffic=daily_traffic,
            num_variants=2,
        )
        if ss_result.get("status") == "error":
            return self._fail(
                f"Sample size calculation failed: {ss_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        sample_size_info = ss_result.get("result", {})
        sample_size_per_variant = int(sample_size_info.get("sample_size_per_variant", 0))

        # ---- Stage 4: Variant Builder ----
        var_result = build_variants(
            control=control,
            treatment=treatment,
            test_type=test_type,
            test_id=str(experiment.get("test_id", "")),
        )
        if var_result.get("status") == "error":
            return self._fail(
                f"Variant building failed: {var_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        variants = var_result.get("variants", [])

        # ---- Stage 5: Traffic Splitter ----
        split_result = split_traffic(
            variants=variants,
            daily_traffic=daily_traffic,
            sample_size_per_variant=sample_size_per_variant,
        )
        if split_result.get("status") == "error":
            return self._fail(
                f"Traffic split failed: {split_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        traffic_split = split_result.get("split", {})

        # ---- Stage 6: Metric Collector ----
        met_result = collect_metrics(
            variants=variants,
            primary_metric=primary_metric,
            current_rate=current_rate,
            mde=mde,
            sample_size_per_variant=sample_size_per_variant,
        )
        if met_result.get("status") == "error":
            return self._fail(
                f"Metric collection failed: {met_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        metrics = met_result.get("metrics", [])

        # ---- Stage 7: Statistical Analyzer (Mistral) ----
        stat_result = analyze_statistics(
            metrics=metrics,
            primary_metric=primary_metric,
            alpha=alpha,
            methodology=str(experiment.get("test_methodology", "two-sample z-test")),
        )
        if stat_result.get("status") == "error":
            return self._fail(
                f"Statistical analysis failed: {stat_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        analysis = stat_result.get("analysis", {})

        # ---- Stage 8: Winner Selector ----
        win_result = select_winner(
            analysis=analysis,
            metrics=metrics,
            mde=mde,
            sample_size_per_variant=sample_size_per_variant,
            required_sample=sample_size_per_variant,
        )
        if win_result.get("status") == "error":
            return self._fail(
                f"Winner selection failed: {win_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        winner = win_result.get("winner", {})

        # ---- Stage 9: Risk Assessor (LLaMA) ----
        risk_result = assess_risk(
            winner=winner,
            analysis=analysis,
            metrics=metrics,
            test_type=test_type,
            segments=segments,
            history=history,
        )
        if risk_result.get("status") == "error":
            return self._fail(
                f"Risk assessment failed: {risk_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        risk = risk_result.get("risk", {})

        # ---- Stage 10: Memory Writer (non-fatal) ----
        _write = write_test_result(
            experiment=experiment,
            winner=winner,
            analysis=analysis,
            test_type=test_type,
            confidence=float(winner.get("confidence", 0.0)),
            input_data=data,
        )

        # ---- Stage 11: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "experiment": experiment,
                "sample_size": sample_size_info.get("total_sample_size", 0),
                "variants": variants,
                "traffic_split": traffic_split,
                "metrics": metrics,
                "analysis": {
                    "p_value": analysis.get("p_value", 1.0),
                    "confidence_interval": analysis.get("confidence_interval", (0.0, 0.0)),
                    "effect_size": analysis.get("effect_size", 0.0),
                    "power": analysis.get("power_achieved", 0.0),
                },
                "winner": winner,
                "risk": risk,
                "confidence": float(winner.get("confidence", 0.0)),
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "test_type": test_type,
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
