"""Customer Behavior Simulator Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Memory Reader → Behavior Modeler → Action Simulator →
  Retention Predictor → LTV Projector → Memory Writer → Output

Engine contract:
  Input:  {status, data: {customers, proposed_actions, historical_data}, meta, error}
  Output: {status, data: {simulations, recommended_actions}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .behavior_modeler import model_customer_behavior
from .action_simulator import simulate_actions
from .retention_predictor import predict_retention
from .ltv_projector import project_ltv
from .memory_reader import read_past_behavior_sims
from .memory_writer import write_behavior_result
from engines._shopify_hydrator import hydrate


class CustomerBehaviorSimulatorEngine:
    """Customer Behavior Simulator Engine — orchestrator only, no logic."""

    ENGINE_NAME = "customer_behavior_simulator"

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
        proposed_actions = data.get("proposed_actions", [])
        historical_data = data.get("historical_data", {})

        # Auto-hydrate customers from Shopify when caller left the
        # list empty. proposed_actions stays caller-supplied (it's
        # the simulation input, not a Shopify resource).
        # Pre-existing failure semantics preserved: empty supplied
        # AND empty hydrated → standard "Customer list is required".
        customers = hydrate(
            supplied=customers if isinstance(customers, list) else [],
            capability_name="SHOPIFY_FETCH_CUSTOMERS",
            list_field="customers",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not customers:
            return self._fail("Customer list is required", 0.0)
        if not proposed_actions:
            return self._fail("At least one proposed action is required", 0.0)

        # ---- Stage 1: Memory Reader ----
        _past = read_past_behavior_sims(limit=5)

        # ---- Stage 2: Behavior Modeler ----
        behavior_result = model_customer_behavior(customers=customers, historical_data=historical_data)
        if behavior_result.get("status") == "error":
            return self._fail(f"Behavior modeling failed: {behavior_result.get('error', 'unknown')}", time.monotonic() - start)
        patterns = behavior_result.get("patterns", [])

        # ---- Stage 3: Action Simulator ----
        action_result = simulate_actions(proposed_actions=proposed_actions, behavior_patterns=patterns)
        if action_result.get("status") == "error":
            return self._fail(f"Action simulation failed: {action_result.get('error', 'unknown')}", time.monotonic() - start)
        simulations = action_result.get("simulations", [])

        # ---- Stage 4: Retention Predictor ----
        retention_result = predict_retention(simulations=simulations, behavior_patterns=patterns)
        if retention_result.get("status") == "error":
            return self._fail(f"Retention prediction failed: {retention_result.get('error', 'unknown')}", time.monotonic() - start)
        retention_predictions = retention_result.get("predictions", [])

        # ---- Stage 5: LTV Projector ----
        ltv_result = project_ltv(simulations=simulations, behavior_patterns=patterns)
        if ltv_result.get("status") == "error":
            return self._fail(f"LTV projection failed: {ltv_result.get('error', 'unknown')}", time.monotonic() - start)
        ltv_projections = ltv_result.get("projections", [])

        # ---- Stage 6: Build recommended actions ----
        # Recommend actions with positive retention AND positive LTV
        recommended: list[str] = []
        for sim in simulations:
            if float(sim.get("predicted_retention_change", 0)) > 0 and float(sim.get("predicted_ltv_change", 0)) > 0:
                recommended.append(f"{sim.get('action', '')} targeting {sim.get('target_segment', '')}")

        # Enrich simulations with retention and LTV detail
        ret_map = {(r.get("segment", ""), r.get("action", "")): r for r in retention_predictions}
        ltv_map = {(l.get("segment", ""), l.get("action", "")): l for l in ltv_projections}
        for sim in simulations:
            key = (sim.get("target_segment", ""), sim.get("action", ""))
            ret = ret_map.get(key, {})
            ltv = ltv_map.get(key, {})
            sim["retention_detail"] = ret
            sim["ltv_detail"] = ltv

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write = write_behavior_result(simulations=simulations, recommended_actions=recommended)

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "simulations": simulations,
                "recommended_actions": recommended,
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
