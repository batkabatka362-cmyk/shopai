"""AutonomousDecision Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Context Evaluator → Option Generator → Outcome Predictor → Decision Selector → Memory Writer → Output

Engine contract:
  Input:  {status, data: {context, options, constraints, goal}, meta, error}
  Output: {status, data: {decision, alternatives, predicted_outcome, confidence, reasoning}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .context_evaluator import evaluate_context
from .option_generator import generate_options
from .outcome_predictor import predict_outcomes
from .decision_selector import select_decision
from .memory_reader import read_past_results
from .memory_writer import write_result


class AutonomousDecisionEngine:
    """AutonomousDecision Engine — orchestrator only, no logic."""

    ENGINE_NAME = "autonomous_decision"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full autonomous decision pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            AutonomousDecisionOutput dict.
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

        context = data.get("context", {})
        options = data.get("options", [])
        constraints = data.get("constraints", {})
        goal = str(data.get("goal", ""))

        if not context:
            return self._fail("Context is required", 0.0)

        # ---- Stage 1: Read past results (non-blocking) ----
        _past = read_past_results(limit=5)

        # ---- Stage 2: Evaluate current context/state ----
        context_evaluator_result = evaluate_context(
            context=context, options=options, constraints=constraints, goal=goal,
        )
        if context_evaluator_result.get("status") == "error":
            return self._fail(
                f"Evaluate current context/state failed: {context_evaluator_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        context_evaluator_data = context_evaluator_result.get("result", {})

        # ---- Stage 3: Generate decision options ----
        option_generator_result = generate_options(
            context=context, options=options, constraints=constraints, goal=goal, context_evaluator_data=context_evaluator_data,
        )
        if option_generator_result.get("status") == "error":
            return self._fail(
                f"Generate decision options failed: {option_generator_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        option_generator_data = option_generator_result.get("result", {})

        # ---- Stage 4: Predict outcome of each option ----
        outcome_predictor_result = predict_outcomes(
            context=context, options=options, constraints=constraints, goal=goal, context_evaluator_data=context_evaluator_data, option_generator_data=option_generator_data,
        )
        if outcome_predictor_result.get("status") == "error":
            return self._fail(
                f"Predict outcome of each option failed: {outcome_predictor_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        outcome_predictor_data = outcome_predictor_result.get("result", {})

        # ---- Stage 5: Select best option ----
        decision_selector_result = select_decision(
            context=context, options=options, constraints=constraints, goal=goal, context_evaluator_data=context_evaluator_data, option_generator_data=option_generator_data, outcome_predictor_data=outcome_predictor_data,
        )
        if decision_selector_result.get("status") == "error":
            return self._fail(
                f"Select best option failed: {decision_selector_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        decision_selector_data = decision_selector_result.get("result", {})

        # ---- Memory Writer (non-fatal) ----
        output_data = {
                "decision": decision_selector_data.get("decision", {}),
                "alternatives": decision_selector_data.get("alternatives", []),
                "predicted_outcome": decision_selector_data.get("predicted_outcome", {}),
                "confidence": decision_selector_data.get("confidence", 0.0),
                "reasoning": decision_selector_data.get("reasoning", ""),
        }
        _write_result = write_result(output_data=output_data)

        # ---- Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": output_data,
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
