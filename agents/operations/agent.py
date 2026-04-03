"""Operations Agent — orchestrates Inventory, Shipping, and Supplier engines.

This is the AGENT file. It ONLY orchestrates — delegates to:
  - planner.py → decides what to do
  - executor.py → calls engines
  - evaluator.py → assesses quality

Agent contract:
  Input:  {goal: str, context: {products, orders, ...}, constraints: {}}
  Output: {status, data: {plan, results, evaluation, recommendation}, meta: {agent, steps}, error}
"""
from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from .planner import create_plan
from .executor import execute_plan
from .evaluator import evaluate_results


class OperationsAgent(BaseAgent):
    """Operations Agent — manages inventory, shipping, suppliers.

    Combines Inventory, Stock Prediction, Supplier, Shipping Optimization,
    and Returns Management engines to answer: "How do we run ops efficiently?"
    """

    def __init__(self) -> None:
        super().__init__(name="operations_agent")

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
        """Generate final recommendation from combined operations data."""
        score = evaluation.get("score", 0)
        quality = evaluation.get("quality", "low")

        engine_results = results.get("engine_results", {})
        inv = engine_results.get("inventory", {})
        sp = engine_results.get("stock_prediction", {})
        sup = engine_results.get("supplier", {})

        # Extract key findings
        findings = []

        # Inventory findings
        if inv.get("status") == "success":
            inv_data = inv.get("data", {})
            if inv_data.get("inventory_health"):
                findings.append(f"Inventory health: {inv_data['inventory_health']}")
            if inv_data.get("stockout_risks"):
                findings.append(f"Stockout risks identified: {len(inv_data['stockout_risks'])} items")

        # Stock prediction findings
        if sp.get("status") == "success":
            sp_data = sp.get("data", {})
            if sp_data.get("stock_forecast"):
                findings.append("Stock forecast generated for planning horizon")

        # Supplier findings
        if sup.get("status") == "success":
            sup_data = sup.get("data", {})
            if sup_data.get("supplier_scores"):
                findings.append("Supplier scores evaluated")

        # Final recommendation
        if score >= 70 and quality == "high":
            action = "place_reorder"
            confidence = "high"
            reason = "Inventory levels and supplier data support immediate reorder"
        elif score >= 50:
            action = "find_backup_supplier"
            confidence = "medium"
            reason = "Operations data shows potential supply chain risks"
        elif score >= 30:
            action = "clear_dead_stock"
            confidence = "medium"
            reason = "Inventory analysis reveals excess stock that should be cleared"
        else:
            action = "no_action_needed"
            confidence = "low"
            reason = "Insufficient data to recommend operational changes"

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
        if action == "place_reorder":
            return [
                "Generate purchase orders for low-stock items",
                "Confirm lead times with preferred suppliers",
                "Update reorder points based on forecast",
                "Schedule receiving and warehousing",
            ]
        if action == "find_backup_supplier":
            return [
                "Run supplier discovery for at-risk categories",
                "Request quotes from alternative suppliers",
                "Evaluate supplier reliability scores",
                "Set up dual-sourcing for critical products",
            ]
        if action == "clear_dead_stock":
            return [
                "Identify slow-moving inventory over 90 days",
                "Create clearance pricing strategy",
                "Bundle dead stock with popular items",
                "Consider liquidation channels",
            ]
        return [
            "Continue monitoring inventory levels",
            "Review operations dashboard weekly",
            "Update demand forecasts with new data",
        ]
