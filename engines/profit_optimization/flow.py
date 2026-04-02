"""Profit Optimization Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input Data → Data Aggregator → Profit Calculator → KPI Analyzer →
  Opportunity Detector → Optimization Generator → Strategy Selector →
  Action Recommender → Risk Analyzer → Scaler → Memory Writer → Output

Engine contract:
  Input:  {status, data: {sales, ads, costs, performance}, meta, error}
  Output: {status, data: {profit, revenue, cost, kpis, ...}, meta: {engine, ...}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .data_aggregator import aggregate_data
from .profit_calculator import calculate_profit
from .kpi_analyzer import analyze_kpis
from .opportunity_detector import detect_opportunities
from .optimization_generator import generate_optimizations
from .strategy_selector import select_strategy
from .action_recommender import recommend_actions
from .risk_analyzer import analyze_risks
from .scaler import evaluate_scaling
from .memory_reader import read_past_optimizations
from .memory_writer import write_optimization_result


class ProfitOptimizationEngine:
    """Profit Optimization Engine — orchestrator only, no logic."""

    ENGINE_NAME = "profit_optimization"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full profit optimization pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ProfitOptimizationOutput dict.
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

        sales = data.get("sales", {})
        ads = data.get("ads", {})
        costs = data.get("costs", {})
        performance = data.get("performance", {})

        if not sales and not costs:
            return self._fail(
                "At least sales or costs data is required", 0.0,
            )

        # ---- Stage 1: Read past optimizations (non-blocking) ----
        past = read_past_optimizations(limit=5)

        # ---- Stage 2: Aggregate data ----
        agg_result = aggregate_data(
            sales=sales,
            ads=ads,
            costs=costs,
            performance=performance,
        )
        if agg_result.get("status") == "error":
            return self._fail(
                f"Data aggregation failed: {agg_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        aggregated = agg_result.get("aggregated", {})

        # ---- Stage 3: Calculate profit ----
        profit_result = calculate_profit(aggregated=aggregated)
        if profit_result.get("status") == "error":
            return self._fail(
                f"Profit calculation failed: {profit_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        profit_metrics = profit_result.get("metrics", {})

        # ---- Stage 4: Analyze KPIs ----
        kpi_result = analyze_kpis(
            aggregated=aggregated,
            profit_metrics=profit_metrics,
        )
        if kpi_result.get("status") == "error":
            return self._fail(
                f"KPI analysis failed: {kpi_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        kpis = kpi_result.get("kpis", {})

        # ---- Stage 5: Detect opportunities ----
        opp_result = detect_opportunities(
            aggregated=aggregated,
            profit_metrics=profit_metrics,
            kpis=kpis,
        )
        opportunities = opp_result.get("opportunities", [])

        # ---- Stage 6: Generate optimizations ----
        opt_result = generate_optimizations(
            opportunities=opportunities,
            aggregated=aggregated,
            profit_metrics=profit_metrics,
            kpis=kpis,
        )
        optimizations = opt_result.get("optimizations", [])

        # ---- Stage 7: Analyze risks ----
        risk_result = analyze_risks(
            optimizations=optimizations,
            aggregated=aggregated,
            profit_metrics=profit_metrics,
        )
        risk_assessments = risk_result.get("assessments", [])

        # ---- Stage 8: Select strategy ----
        strategy_result = select_strategy(
            optimizations=optimizations,
            risk_assessments=risk_assessments,
            profit_metrics=profit_metrics,
            kpis=kpis,
        )
        selected_strategy = strategy_result.get("strategy", {})

        # ---- Stage 9: Recommend actions ----
        action_result = recommend_actions(
            selected_strategy=selected_strategy,
            optimizations=optimizations,
            risk_assessments=risk_assessments,
            aggregated=aggregated,
            profit_metrics=profit_metrics,
        )
        recommended_actions = action_result.get("actions", [])

        # ---- Stage 10: Evaluate scaling ----
        scale_result = evaluate_scaling(
            aggregated=aggregated,
            profit_metrics=profit_metrics,
            kpis=kpis,
            optimizations=optimizations,
        )
        scaling = scale_result.get("scaling", {})

        # ---- Stage 11: Write to memory (non-fatal) ----
        _write_result = write_optimization_result(
            profit_metrics=profit_metrics,
            kpis=kpis,
            selected_strategy=selected_strategy,
            recommended_actions=recommended_actions,
            confidence=float(selected_strategy.get("confidence", 0.0)),
        )

        # ---- Stage 12: Assemble output ----
        elapsed = time.monotonic() - start

        overall_risk = self._compute_overall_risk(risk_assessments)
        overall_confidence = float(selected_strategy.get("confidence", 0.0))

        return {
            "status": "success",
            "data": {
                "profit": float(profit_metrics.get("net_profit", 0.0)),
                "revenue": float(profit_metrics.get("net_revenue", 0.0)),
                "cost": float(profit_metrics.get("total_cost", 0.0)),
                "kpis": kpis,
                "opportunities": opportunities,
                "optimizations": optimizations,
                "selected_strategy": selected_strategy,
                "recommended_actions": recommended_actions,
                "risk_assessments": risk_assessments,
                "scaling": scaling,
                "risk_level": overall_risk,
                "confidence": overall_confidence,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Output assembly helpers (pure data shaping, no business logic)
    # -------------------------------------------------------------------

    def _compute_overall_risk(
        self, risk_assessments: list[dict[str, Any]],
    ) -> str:
        """Derive overall risk level from individual assessments."""
        if not risk_assessments:
            return "unknown"

        risk_scores = [
            float(a.get("overall_risk", 0.5)) for a in risk_assessments
        ]
        avg_risk = sum(risk_scores) / len(risk_scores)

        if avg_risk >= 0.7:
            return "high"
        if avg_risk >= 0.4:
            return "medium"
        return "low"

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
