"""Selection Reasoning Engine — orchestrates the complete reasoning pipeline.

Flow: narrative_builder -> data_citation -> risk_disclosure -> alternative_presenter -> action_planner

Each module receives the cumulative context and adds its output.
The engine returns a comprehensive reasoning report explaining
why the product was selected, what data supports the decision,
what risks exist, what alternatives were considered, and what
to do next.
"""
from __future__ import annotations

import time
from typing import Any

from .input.handler import validate_and_standardize
from .output.formatter import format_output
from .validation.validator import validate_result
from .modules.narrative_builder.code import build_narrative
from .modules.data_citation.code import cite_data
from .modules.risk_disclosure.code import disclose_risks
from .modules.alternative_presenter.code import present_alternatives
from .modules.action_planner.code import create_action_plan


class SelectionReasoningEngine:
    """Selection Reasoning — orchestrator for the full reasoning pipeline."""

    ENGINE_NAME = "selection_reasoning"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Execute the selection reasoning pipeline.

        Args:
            input_payload: {
                data: {
                    selected_product: dict  — the chosen product with scores
                    backup_product: dict    — runner-up product (optional)
                    all_products: list      — all evaluated candidates
                    decision_rationale: dict — why the product was chosen
                    engine_results: dict    — outputs from all upstream engines
                    confidence: dict        — confidence assessment
                    goal: str               — profit|growth|balanced
                    investment: float       — estimated initial investment
                    product_type: str       — product category
                }
            }

        Returns:
            Engine contract: {status, data, meta, error}
        """
        start = time.monotonic()

        # --- Input validation ---
        processed = validate_and_standardize(input_payload)
        if processed["status"] == "fail":
            return processed

        data = processed["data"]
        results: dict[str, Any] = {}

        selected = data.get("selected_product", {})
        goal = data.get("goal", "balanced")
        investment = data.get("investment", 5000.0)
        product_type = data.get("product_type", "general")

        # --- Module 1: Narrative Builder ---
        try:
            results["narrative"] = build_narrative({
                "selected_product": selected,
                "backup_product": data.get("backup_product", {}),
                "decision_rationale": data.get("decision_rationale", {}),
                "engine_results": data.get("engine_results", {}),
                "confidence": data.get("confidence", {}),
                "goal": goal,
            })
        except Exception as exc:
            results["narrative"] = _module_error("narrative_builder", exc)

        # --- Module 2: Data Citation ---
        try:
            results["citations"] = cite_data({
                "selected_product": selected,
                "engine_results": data.get("engine_results", {}),
                "decision_rationale": data.get("decision_rationale", {}),
                "goal": goal,
            })
        except Exception as exc:
            results["citations"] = _module_error("data_citation", exc)

        # --- Module 3: Risk Disclosure ---
        try:
            results["risk_disclosure"] = disclose_risks({
                "selected_product": selected,
                "engine_results": data.get("engine_results", {}),
                "investment": investment,
                "confidence": data.get("confidence", {}),
                "goal": goal,
            })
        except Exception as exc:
            results["risk_disclosure"] = _module_error("risk_disclosure", exc)

        # --- Module 4: Alternative Presenter ---
        try:
            results["alternatives"] = present_alternatives({
                "selected_product": selected,
                "all_products": data.get("all_products", []),
                "goal": goal,
            })
        except Exception as exc:
            results["alternatives"] = _module_error("alternative_presenter", exc)

        # --- Module 5: Action Planner ---
        try:
            results["action_plan"] = create_action_plan({
                "selected_product": selected,
                "investment": investment,
                "product_type": product_type,
                "goal": goal,
                "start_date": data.get("start_date"),
            })
        except Exception as exc:
            results["action_plan"] = _module_error("action_planner", exc)

        elapsed = time.monotonic() - start

        # --- Format and validate output ---
        output = format_output(self.ENGINE_NAME, results, data, elapsed)
        validation = validate_result(output)
        if not validation["valid"]:
            return {
                "status": "fail",
                "data": None,
                "meta": {
                    "engine": self.ENGINE_NAME,
                    "confidence": 0,
                    "timestamp": _now(),
                },
                "error": {"reason": validation["reason"]},
            }

        return output


def _module_error(module_name: str, exc: Exception) -> dict[str, Any]:
    """Return a standardized module error response."""
    return {
        "status": "error",
        "data": {},
        "meta": {"module": module_name},
        "error": {"type": type(exc).__name__, "message": str(exc)},
    }


def _now() -> str:
    """Return the current UTC timestamp."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
