"""Simulation Lab — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Scenario Generator → Environment Model → Simulation Engine →
  Outcome Predictor → Result Analyzer → Risk Estimator →
  Performance Estimator → Strategy Comparator → Best Option Selector →
  Memory Writer → Output

Engine contract:
  Input:  {status, data: {strategy_type, base_parameters, ...}, meta, error}
  Output: {status, data: {best_option, all_scenarios, ...}, meta: {engine, ...}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .scenario_generator import generate_scenarios
from .environment_model import compute_environment_factors
from .simulation_engine import run_simulations
from .outcome_predictor import predict_outcomes
from .result_analyzer import analyze_results
from .risk_estimator import estimate_risks
from .performance_estimator import estimate_performance
from .strategy_comparator import compare_strategies
from .best_option_selector import select_best_option
from .memory_reader import read_past_simulations, compute_input_hash
from .memory_writer import write_simulation_result


class SimulationLabEngine:
    """Simulation Lab Engine — orchestrator only, no logic."""

    ENGINE_NAME = "simulation_lab"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full simulation lab pipeline.

        Args:
            input_payload: SimulationInput dict.

        Returns:
            SimulationLabOutput dict.
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

        strategy_type = str(data.get("strategy_type", "general"))
        base_parameters = data.get("base_parameters", {})
        constraints = data.get("constraints", {})
        objectives = data.get("objectives", ["revenue", "profit", "risk"])
        num_scenarios = int(data.get("num_scenarios", 5))
        iterations = int(data.get("iterations_per_scenario", 200))
        environment = data.get("environment", {})

        if not base_parameters:
            return self._fail("base_parameters is required and must not be empty", 0.0)

        # ---- Stage 1: Read past simulations (non-blocking) ----
        input_hash = compute_input_hash(data)
        _past = read_past_simulations(strategy_type=strategy_type, limit=5)

        # ---- Stage 2: Generate scenarios ----
        scenario_result = generate_scenarios(
            strategy_type=strategy_type,
            base_parameters=base_parameters,
            constraints=constraints,
            objectives=objectives,
            num_scenarios=num_scenarios,
        )
        if scenario_result.get("status") == "error":
            return self._fail(
                f"Scenario generation failed: {scenario_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        scenarios = scenario_result.get("scenarios", [])
        if not scenarios:
            return self._fail("No scenarios generated", time.monotonic() - start)

        # ---- Stage 3: Compute environment factors ----
        env_result = compute_environment_factors(
            environment=environment,
            strategy_type=strategy_type,
        )
        env_factors = env_result.get("factors", {})

        # ---- Stage 4: Run Monte Carlo simulations ----
        sim_result = run_simulations(
            scenarios=scenarios,
            environment_factors=env_factors,
            iterations=iterations,
        )
        if sim_result.get("status") == "error":
            return self._fail(
                f"Simulation failed: {sim_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        sim_results = sim_result.get("results", [])

        # ---- Stage 5: Predict outcomes ----
        pred_result = predict_outcomes(
            simulation_results=sim_results,
            scenarios=scenarios,
            environment_factors=env_factors,
        )
        predictions = pred_result.get("predictions", [])

        # ---- Stage 6: Analyze results ----
        analysis_result = analyze_results(
            simulation_results=sim_results,
            predictions=predictions,
            scenarios=scenarios,
        )
        analyses = analysis_result.get("analyses", [])

        # ---- Stage 7: Estimate risks ----
        risk_result = estimate_risks(
            simulation_results=sim_results,
            predictions=predictions,
            environment_factors=env_factors,
        )
        risk_assessments = risk_result.get("assessments", [])

        # ---- Stage 8: Estimate performance ----
        perf_result = estimate_performance(
            simulation_results=sim_results,
            predictions=predictions,
            scenarios=scenarios,
            environment_factors=env_factors,
        )
        perf_estimates = perf_result.get("estimates", [])

        # ---- Stage 9: Compare strategies ----
        comp_result = compare_strategies(
            predictions=predictions,
            analyses=analyses,
            risk_assessments=risk_assessments,
            performance_estimates=perf_estimates,
            scenarios=scenarios,
            objectives=objectives,
        )
        comparison = comp_result.get("comparison", [])

        # ---- Stage 10: Select best option ----
        selection_result = select_best_option(
            comparison=comparison,
            predictions=predictions,
            risk_assessments=risk_assessments,
            scenarios=scenarios,
            objectives=objectives,
        )
        best_option = selection_result.get("best_option", {})

        # ---- Stage 11: Write to memory (non-fatal) ----
        _write_result = write_simulation_result(
            strategy_type=strategy_type,
            input_hash=input_hash,
            best_option=best_option,
            all_scenarios=scenarios,
            confidence=float(best_option.get("confidence", 0.0)),
        )

        # ---- Stage 12: Assemble output ----
        elapsed = time.monotonic() - start

        # Build scenario summaries (strip raw iterations to keep output lean)
        all_scenarios_summary = self._build_scenario_summaries(
            scenarios, sim_results, predictions, analyses,
            risk_assessments, perf_estimates, comparison,
        )

        # Aggregate risk assessment
        risk_summary = self._build_risk_summary(risk_assessments)

        # Aggregate performance forecast
        perf_summary = self._build_performance_summary(perf_estimates)

        overall_confidence = float(best_option.get("confidence", 0.0))

        return {
            "status": "success",
            "data": {
                "best_option": best_option,
                "all_scenarios": all_scenarios_summary,
                "risk_assessment": risk_summary,
                "performance_forecast": perf_summary,
                "confidence": overall_confidence,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "scenarios_tested": len(scenarios),
                "iterations_per_scenario": iterations,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Output assembly helpers (pure data shaping, no business logic)
    # -------------------------------------------------------------------

    def _build_scenario_summaries(
        self,
        scenarios: list[dict],
        sim_results: list[dict],
        predictions: list[dict],
        analyses: list[dict],
        risk_assessments: list[dict],
        perf_estimates: list[dict],
        comparison: list[dict],
    ) -> list[dict[str, Any]]:
        """Merge per-scenario data into compact summaries."""
        sim_map = {r["scenario_id"]: r for r in sim_results}
        pred_map = {p["scenario_id"]: p for p in predictions}
        anal_map = {a["scenario_id"]: a for a in analyses}
        risk_map = {r["scenario_id"]: r for r in risk_assessments}
        perf_map = {e["scenario_id"]: e for e in perf_estimates}
        comp_map = {c["scenario_id"]: c for c in comparison}

        summaries: list[dict[str, Any]] = []
        for scenario in scenarios:
            sid = scenario["scenario_id"]
            sim = sim_map.get(sid, {})
            pred = pred_map.get(sid, {})
            anal = anal_map.get(sid, {})
            risk = risk_map.get(sid, {})
            perf = perf_map.get(sid, {})
            comp = comp_map.get(sid, {})

            summaries.append({
                "scenario_id": sid,
                "label": scenario.get("label", sid),
                "variation_type": scenario.get("variation_type", ""),
                "parameters": scenario.get("parameters", {}),
                "simulation": {
                    "mean_revenue": sim.get("mean_revenue", 0.0),
                    "mean_profit": sim.get("mean_profit", 0.0),
                    "mean_margin": sim.get("mean_margin", 0.0),
                    "std_revenue": sim.get("std_revenue", 0.0),
                    "revenue_p5": sim.get("revenue_p5", 0.0),
                    "revenue_p95": sim.get("revenue_p95", 0.0),
                },
                "prediction": {
                    "predicted_revenue": pred.get("predicted_revenue", 0.0),
                    "predicted_profit": pred.get("predicted_profit", 0.0),
                    "predicted_risk": pred.get("predicted_risk", 0.0),
                    "confidence": pred.get("confidence", 0.0),
                },
                "analysis": {
                    "strengths": anal.get("strengths", []),
                    "weaknesses": anal.get("weaknesses", []),
                    "stability_score": anal.get("stability_score", 0.0),
                },
                "risk": {
                    "overall_risk": risk.get("overall_risk", 0.0),
                    "risk_category": risk.get("risk_category", "unknown"),
                    "probability_of_loss": risk.get("probability_of_loss", 0.0),
                },
                "performance": {
                    "expected_roi": perf.get("expected_roi", 0.0),
                    "growth_potential": perf.get("growth_potential", 0.0),
                    "scalability_score": perf.get("scalability_score", 0.0),
                },
                "rank": comp.get("rank", 0),
                "total_score": comp.get("total_score", 0.0),
            })

        summaries.sort(key=lambda s: s.get("rank", 999))
        return summaries

    def _build_risk_summary(
        self, risk_assessments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Aggregate risk assessments into a summary."""
        if not risk_assessments:
            return {"overall": "unknown", "details": []}

        risks = [float(r.get("overall_risk", 0.5)) for r in risk_assessments]
        avg_risk = sum(risks) / len(risks)
        max_risk = max(risks)
        min_risk = min(risks)

        loss_probs = [float(r.get("probability_of_loss", 0.0)) for r in risk_assessments]
        avg_loss_prob = sum(loss_probs) / len(loss_probs)

        categories = [r.get("risk_category", "unknown") for r in risk_assessments]
        category_counts = {}
        for cat in categories:
            category_counts[cat] = category_counts.get(cat, 0) + 1

        return {
            "average_risk": round(avg_risk, 4),
            "max_risk": round(max_risk, 4),
            "min_risk": round(min_risk, 4),
            "average_loss_probability": round(avg_loss_prob, 4),
            "risk_distribution": category_counts,
            "scenarios_assessed": len(risk_assessments),
        }

    def _build_performance_summary(
        self, perf_estimates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Aggregate performance estimates into a summary."""
        if not perf_estimates:
            return {"overall": "unknown", "details": []}

        revenues = [float(e.get("expected_revenue", 0.0)) for e in perf_estimates]
        profits = [float(e.get("expected_profit", 0.0)) for e in perf_estimates]
        rois = [float(e.get("expected_roi", 0.0)) for e in perf_estimates]
        growth = [float(e.get("growth_potential", 0.0)) for e in perf_estimates]
        scalability = [float(e.get("scalability_score", 0.0)) for e in perf_estimates]

        n = len(perf_estimates)
        return {
            "avg_expected_revenue": round(sum(revenues) / n, 2),
            "avg_expected_profit": round(sum(profits) / n, 2),
            "avg_expected_roi": round(sum(rois) / n, 4),
            "avg_growth_potential": round(sum(growth) / n, 4),
            "avg_scalability_score": round(sum(scalability) / n, 4),
            "best_revenue": round(max(revenues), 2),
            "best_profit": round(max(profits), 2),
            "scenarios_estimated": n,
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
                "scenarios_tested": 0,
                "iterations_per_scenario": 0,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
