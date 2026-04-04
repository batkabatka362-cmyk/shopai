"""Market Simulator Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Memory Reader → Demand Modeler → Price Impact Simulator →
  Launch Simulator → Scenario Comparator → Memory Writer → Output

Engine contract:
  Input:  {status, data: {product, scenarios, market_data}, meta, error}
  Output: {status, data: {simulations, best_scenario, risk_analysis}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .demand_modeler import model_demand
from .price_impact_simulator import simulate_price_impact
from .launch_simulator import simulate_launch
from .scenario_comparator import compare_scenarios
from .memory_reader import read_past_simulations
from .memory_writer import write_simulation_result


class MarketSimulatorEngine:
    """Market Simulator Engine — orchestrator only, no logic."""

    ENGINE_NAME = "market_simulator"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full market simulation pipeline."""
        start = time.monotonic()

        # ---- Stage 0: Input validation ----
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

        product = data.get("product", {})
        scenarios = data.get("scenarios", [])
        market_data = data.get("market_data", {})

        if not product:
            return self._fail("Product data is required", 0.0)
        if not scenarios:
            return self._fail("At least one scenario is required", 0.0)

        # ---- Stage 1: Read past simulations (non-blocking) ----
        _past = read_past_simulations(limit=5)

        # ---- Stage 2: Demand Modeler ----
        demand_result = model_demand(product=product, market_data=market_data)
        if demand_result.get("status") == "error":
            return self._fail(
                f"Demand modeling failed: {demand_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        demand_model = demand_result.get("demand_model", {})

        # ---- Stage 3: Price Impact Simulator ----
        impact_result = simulate_price_impact(
            scenarios=scenarios, demand_model=demand_model, product=product,
        )
        if impact_result.get("status") == "error":
            return self._fail(
                f"Price impact simulation failed: {impact_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        price_impacts = impact_result.get("impacts", [])

        # ---- Stage 4: Launch Simulator ----
        launch_result = simulate_launch(
            scenarios=scenarios, demand_model=demand_model,
            product=product, market_data=market_data,
        )
        if launch_result.get("status") == "error":
            return self._fail(
                f"Launch simulation failed: {launch_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        launch_simulations = launch_result.get("simulations", [])

        # ---- Stage 5: Scenario Comparator ----
        compare_result = compare_scenarios(
            price_impacts=price_impacts,
            launch_simulations=launch_simulations,
            demand_model=demand_model,
        )
        if compare_result.get("status") == "error":
            return self._fail(
                f"Scenario comparison failed: {compare_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        comparisons = compare_result.get("comparisons", [])
        best_scenario = compare_result.get("best_scenario", "")
        risk_analysis = compare_result.get("risk_analysis", {})

        # ---- Stage 6: Build simulations output ----
        simulations = [
            {
                "scenario": c.get("scenario", ""),
                "predicted_revenue": c.get("predicted_revenue", 0),
                "predicted_units": c.get("predicted_units", 0),
                "confidence": c.get("confidence", 0),
            }
            for c in comparisons
        ]

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write = write_simulation_result(
            simulations=simulations,
            best_scenario=best_scenario,
            risk_analysis=risk_analysis,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "simulations": simulations,
                "best_scenario": best_scenario,
                "risk_analysis": risk_analysis,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

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
