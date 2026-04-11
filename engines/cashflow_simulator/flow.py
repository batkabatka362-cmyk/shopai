"""Cashflow Simulator Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Memory Reader → Revenue Projector → Cost Projector →
  Scenario Builder → Viability Assessor → Memory Writer → Output

Engine contract:
  Input:  {status, data: {current_balance, monthly_revenue, monthly_costs, growth_rate, seasonality}, meta, error}
  Output: {status, data: {projections, scenarios, viability}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .revenue_projector import project_revenue
from .cost_projector import project_costs
from .scenario_builder import build_scenarios
from .viability_assessor import assess_viability
from .memory_reader import read_past_cashflows
from .memory_writer import write_cashflow_result


class CashflowSimulatorEngine:
    """Cashflow Simulator Engine — orchestrator only, no logic."""

    ENGINE_NAME = "cashflow_simulator"

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

        current_balance = float(data.get("current_balance", 0.0))
        monthly_revenue = float(data.get("monthly_revenue", 0.0))
        monthly_costs = float(data.get("monthly_costs", 0.0))
        growth_rate = float(data.get("growth_rate", 0.0))
        seasonality = data.get("seasonality", {})

        if monthly_revenue <= 0 and monthly_costs <= 0:
            return self._fail("Monthly revenue or costs must be provided", 0.0)

        # ---- Stage 1: Memory Reader ----
        _past = read_past_cashflows(limit=5)

        # ---- Stage 2: Revenue Projector ----
        rev_result = project_revenue(monthly_revenue=monthly_revenue, growth_rate=growth_rate, seasonality=seasonality)
        if rev_result.get("status") == "error":
            return self._fail(f"Revenue projection failed: {rev_result.get('error', 'unknown')}", time.monotonic() - start)
        revenue_projections = rev_result.get("projections", [])

        # ---- Stage 3: Cost Projector ----
        cost_result = project_costs(monthly_costs=monthly_costs, revenue_projections=revenue_projections, monthly_revenue=monthly_revenue)
        if cost_result.get("status") == "error":
            return self._fail(f"Cost projection failed: {cost_result.get('error', 'unknown')}", time.monotonic() - start)
        cost_projections = cost_result.get("projections", [])

        # ---- Stage 4: Scenario Builder ----
        scenario_result = build_scenarios(revenue_projections=revenue_projections, cost_projections=cost_projections, current_balance=current_balance)
        if scenario_result.get("status") == "error":
            return self._fail(f"Scenario building failed: {scenario_result.get('error', 'unknown')}", time.monotonic() - start)
        scenarios = scenario_result.get("scenarios", {})

        # ---- Stage 5: Viability Assessor ----
        viability_result = assess_viability(scenarios=scenarios, current_balance=current_balance, monthly_costs=monthly_costs)
        if viability_result.get("status") == "error":
            return self._fail(f"Viability assessment failed: {viability_result.get('error', 'unknown')}", time.monotonic() - start)
        viability = viability_result.get("viability", {})

        # ---- Stage 6: Build expected projections for output ----
        expected = scenarios.get("expected", {})
        projections = expected.get("projections", [])

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write = write_cashflow_result(projections=projections, scenarios=scenarios, viability=viability)

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "projections": projections,
                "scenarios": {"best": scenarios.get("best", {}), "worst": scenarios.get("worst", {}), "expected": expected},
                "viability": viability,
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
