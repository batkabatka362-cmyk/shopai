"""Finance Agent — orchestrates profit optimization, forecasting, and pricing engines.

This is the AGENT file. It ONLY orchestrates — delegates to:
  - planner.py → decides what to do
  - executor.py → calls engines
  - evaluator.py → assesses quality

Agent contract:
  Input:  {goal: str, context: {orders, products, costs, ...}, constraints: {}}
  Output: {status, data: {plan, results, evaluation, recommendation}, meta: {agent, steps}, error}
"""
from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from .planner import create_plan
from .executor import execute_plan
from .evaluator import evaluate_results


class FinanceAgent(BaseAgent):
    """Finance Agent — optimizes profit, forecasts, manages pricing and discounts.

    Combines financial analysis, KPI tracking, forecasting, pricing,
    dynamic pricing, elasticity, discount, and profitability engines to answer:
    "How do we maximize profit and financial health?"
    """

    def __init__(self) -> None:
        super().__init__(name="finance_agent")

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
        """Generate final recommendation from combined financial analysis."""
        score = evaluation.get("score", 0)
        quality = evaluation.get("quality", "low")

        engine_results = results.get("engine_results", {})
        financial = engine_results.get("financial", {})
        pricing = engine_results.get("pricing", {})
        forecasting = engine_results.get("forecasting", {})

        # Extract key findings
        findings = []

        if financial.get("status") == "success":
            f_data = financial.get("data", {})
            if f_data.get("health_grade"):
                findings.append(f"Financial health grade: {f_data['health_grade']}")
            if f_data.get("margins"):
                findings.append(f"Current margins: {f_data['margins']}")

        if pricing.get("status") == "success":
            p_data = pricing.get("data", {})
            recs = p_data.get("price_recommendations", [])
            if recs:
                findings.append(f"Generated {len(recs)} pricing recommendations")

        if forecasting.get("status") == "success":
            fc_data = forecasting.get("data", {})
            if fc_data.get("revenue_forecast"):
                findings.append("Revenue forecast generated")

        # Final recommendation
        if score >= 70 and quality == "high":
            action = "increase_prices"
            confidence = "high"
            reason = "Financial analysis and pricing data support price increases"
        elif score >= 50:
            action = "maintain"
            confidence = "medium"
            reason = "Financial health is stable — maintain current strategy with monitoring"
        elif score >= 30:
            action = "cut_costs"
            confidence = "medium"
            reason = "Margins are tight — focus on cost reduction before pricing changes"
        else:
            action = "restructure_discounts"
            confidence = "low"
            reason = "Financial health is poor — restructure discounts and pricing immediately"

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
        if action == "increase_prices":
            return [
                "Apply recommended price increases to top-margin products",
                "Monitor conversion rates after price changes",
                "Set up price elasticity tracking",
                "Review competitor pricing monthly",
            ]
        if action == "maintain":
            return [
                "Continue monitoring KPI trends weekly",
                "Review forecasts quarterly",
                "Track margin changes across product categories",
                "Prepare contingency plans for margin erosion",
            ]
        if action == "cut_costs":
            return [
                "Review supplier costs and negotiate better rates",
                "Identify low-margin products for pruning",
                "Optimize shipping and fulfillment costs",
                "Reduce marketing spend on underperforming channels",
            ]
        return [
            "Audit all active discount codes and promotions",
            "Eliminate unprofitable discount tiers",
            "Set minimum margin thresholds for all products",
            "Implement dynamic pricing to protect margins",
        ]
