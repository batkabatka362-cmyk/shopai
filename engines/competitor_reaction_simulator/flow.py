"""Competitor Reaction Simulator Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Memory Reader → Behavior Modeler → Reaction Predictor →
  Game Theorizer → Counterstrategy Builder → Memory Writer → Output

Engine contract:
  Input:  {status, data: {our_action, competitors, market_data, history}, meta, error}
  Output: {status, data: {predictions, nash_equilibrium, recommended_counterstrategy}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .behavior_modeler import model_behavior
from .reaction_predictor import predict_reactions
from .game_theorizer import analyze_game_theory
from .counterstrategy_builder import build_counterstrategy
from .memory_reader import read_past_reactions
from .memory_writer import write_reaction_result


class CompetitorReactionSimulatorEngine:
    """Competitor Reaction Simulator Engine — orchestrator only, no logic."""

    ENGINE_NAME = "competitor_reaction_simulator"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full competitor reaction simulation pipeline."""
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

        our_action = data.get("our_action", {})
        competitors = data.get("competitors", [])
        market_data = data.get("market_data", {})
        history = data.get("history", [])

        if not our_action:
            return self._fail("Our action is required", 0.0)
        if not competitors:
            return self._fail("Competitor list is required", 0.0)

        # ---- Stage 1: Read past reactions (non-blocking) ----
        _past = read_past_reactions(limit=5)

        # ---- Stage 2: Behavior Modeler ----
        behavior_result = model_behavior(competitors=competitors, history=history)
        if behavior_result.get("status") == "error":
            return self._fail(f"Behavior modeling failed: {behavior_result.get('error', 'unknown')}", time.monotonic() - start)
        behavior_models = behavior_result.get("models", [])

        # ---- Stage 3: Reaction Predictor ----
        reaction_result = predict_reactions(our_action=our_action, behavior_models=behavior_models)
        if reaction_result.get("status") == "error":
            return self._fail(f"Reaction prediction failed: {reaction_result.get('error', 'unknown')}", time.monotonic() - start)
        predictions = reaction_result.get("predictions", [])

        # ---- Stage 4: Game Theorizer ----
        game_result = analyze_game_theory(our_action=our_action, predictions=predictions, market_data=market_data)
        if game_result.get("status") == "error":
            return self._fail(f"Game theory analysis failed: {game_result.get('error', 'unknown')}", time.monotonic() - start)
        nash_equilibrium = game_result.get("nash_equilibrium", {})

        # ---- Stage 5: Counterstrategy Builder ----
        counter_result = build_counterstrategy(predictions=predictions, nash_equilibrium=nash_equilibrium, our_action=our_action)
        if counter_result.get("status") == "error":
            return self._fail(f"Counterstrategy building failed: {counter_result.get('error', 'unknown')}", time.monotonic() - start)
        counterstrategy = counter_result.get("counterstrategy", {})

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write = write_reaction_result(predictions=predictions, nash_equilibrium=nash_equilibrium, counterstrategy=counterstrategy)

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "predictions": predictions,
                "nash_equilibrium": nash_equilibrium,
                "recommended_counterstrategy": counterstrategy,
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
