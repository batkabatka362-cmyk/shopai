"""Product Agent — orchestrates product discovery, scoring, pricing, and launch engines.

This is the AGENT file. It ONLY orchestrates — delegates to:
  - planner.py → decides what to do
  - executor.py → calls engines
  - evaluator.py → assesses quality

Agent contract:
  Input:  {goal: str, context: {products, criteria, ...}, constraints: {}}
  Output: {status, data: {plan, results, evaluation, recommendation}, meta: {agent, steps}, error}
"""
from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from .planner import create_plan
from .executor import execute_plan
from .evaluator import evaluate_results


class ProductAgent(BaseAgent):
    """Product Agent — finds, filters, scores, prices, and launches products.

    Combines product filtering, scoring, validation, ranking, pricing,
    profitability, and catalog engines to answer:
    "Which products should we sell, at what price?"
    """

    def __init__(self) -> None:
        super().__init__(name="product_agent")

    def plan(self, goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
        """Delegate planning to planner module."""
        return create_plan(goal, context, constraints)

    def execute(self, plan: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Delegate execution to executor module."""
        return execute_plan(plan, context)

    def evaluate(self, results: dict[str, Any], goal: str) -> dict[str, Any]:
        """Delegate evaluation to evaluator module."""
        return evaluate_results(results, goal)

    def recommend(self, results: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
        """Generate final recommendation from combined product analysis."""
        score = evaluation.get("score", 0)
        quality = evaluation.get("quality", "low")

        engine_results = results.get("engine_results", {})
        scoring = engine_results.get("product_scoring", {})
        pricing = engine_results.get("pricing", {})
        validation = engine_results.get("product_validation", {})

        # Extract key findings
        findings = []

        if scoring.get("status") == "success":
            s_data = scoring.get("data", {})
            scored = s_data.get("scored_products", [])
            if scored:
                findings.append(f"Scored {len(scored)} products")

        if pricing.get("status") == "success":
            p_data = pricing.get("data", {})
            recs = p_data.get("price_recommendations", [])
            if recs:
                findings.append(f"Generated {len(recs)} price recommendations")

        if validation.get("status") == "success":
            v_data = validation.get("data", {})
            validated = v_data.get("validated_products", [])
            if validated:
                findings.append(f"Validated {len(validated)} products")

        # Final recommendation
        if score >= 70 and quality == "high":
            action = "launch_products"
            confidence = "high"
            reason = "Product scoring, pricing, and validation all support launch"
        elif score >= 40:
            action = "refine_selection"
            confidence = "medium"
            reason = "Some products look promising but selection needs refinement"
        else:
            action = "drop_category"
            confidence = "low"
            reason = "Insufficient product quality or pricing viability"

        return {
            "action": action,
            "confidence": confidence,
            "reason": reason,
            "findings": findings,
            "next_steps": self._next_steps(action),
            "quality_score": score,
        }

    def _next_steps(self, action: str) -> list[str]:
        """Generate specific next steps based on recommendation."""
        if action == "launch_products":
            return [
                "Finalize pricing and margins",
                "Create product listings in catalog",
                "Set up marketing campaigns for launch",
                "Configure inventory and supplier orders",
            ]
        if action == "refine_selection":
            return [
                "Review scoring criteria and adjust weights",
                "Gather more market data on borderline products",
                "Run validation on top candidates again",
                "Consider alternative products in same category",
            ]
        return [
            "Evaluate alternative product categories",
            "Run research agent on new niches",
            "Review competitor product mix for ideas",
        ]
