"""DecisionNarrativeGenerator — explains decisions in plain language.

Converts raw decision data like {"action": "increase_price", "new_price": 35}
into human-readable business narratives:

"We're raising Widget X price from $29 to $35.
 Why: Demand up 40%, supplier costs up $2.50, competitors at $38-42.
 Risk: 8-12% volume decrease possible.
 Alternative: Hold price → margin drops to 32%."

Template-based — no AI model needed.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("intelligence.narrator")


class DecisionNarrator:
    """Generates plain-language narratives for system decisions.

    Usage:
        narrator = DecisionNarrator()
        narrative = narrator.narrate(cycle_result)
        explanation = narrator.explain_decision(decision, analysis, goal)
    """

    def narrate(self, cycle_result: dict[str, Any]) -> str:
        """Generate a full narrative for a cycle result."""
        summary = cycle_result.get("summary", {})
        phases = cycle_result.get("phases", {})
        priorities = cycle_result.get("priorities", [])
        judgment = phases.get("judgment", {})

        parts = []

        # Goal
        goal = summary.get("strategy_goal", cycle_result.get("goal", "maximize_profit"))
        parts.append(f"Goal: {self._goal_narrative(goal)}")

        # Decision
        decision = summary.get("decision", "none")
        confidence = summary.get("confidence", "unknown")
        score = summary.get("confidence_score", 0)
        if decision != "none":
            parts.append(f"\nDecision: {decision}")
            parts.append(f"Confidence: {confidence} ({score}/100)")

        # Reason
        reason = summary.get("decision_reason", "")
        if reason:
            parts.append(f"\nWhy: {reason}")

        # Financial
        profit = summary.get("net_profit", 0)
        grade = summary.get("health_grade", "?")
        if profit and profit != "?":
            parts.append(f"\nFinancials: ${profit:,.2f} net profit, health grade {grade}")

        # Priorities
        if priorities:
            critical = [p for p in priorities if p.get("urgency") in ("critical", "high")]
            if critical:
                parts.append(f"\nUrgent issues:")
                for p in critical[:3]:
                    parts.append(f"  - [{p['urgency'].upper()}] {p['domain']}: {p.get('reason', '?')}")

        # Judgment
        verdict = judgment.get("verdict", "")
        if verdict and verdict != "proceed":
            parts.append(f"\nJudgment: {verdict.upper()} — {judgment.get('reason', '')}")
            for rec in judgment.get("recommendations", []):
                parts.append(f"  Recommendation: {rec}")

        # Data quality
        dq = summary.get("data_quality", 0)
        if dq > 0:
            parts.append(f"\nData quality: {dq}/100")

        return "\n".join(parts)

    def explain_decision(
        self,
        decision: dict[str, Any],
        analysis: dict[str, Any] | None = None,
        goal: str = "",
    ) -> str:
        """Generate a focused explanation for a single decision."""
        action = decision.get("action", "No action")
        confidence = decision.get("confidence", "unknown")
        score = decision.get("confidence_score", 0)
        reason = decision.get("reason", "")
        options = decision.get("options_evaluated", 0)

        parts = [f"What: {action}"]

        if reason:
            parts.append(f"Why: {reason}")

        if goal:
            parts.append(f"Goal alignment: This action serves '{self._goal_narrative(goal)}'")

        parts.append(f"Confidence: {confidence} ({score}/100)")

        if options > 1:
            parts.append(f"Considered {options} alternatives before choosing this action")

        # Add analysis context if available
        if analysis:
            context_parts = self._extract_analysis_context(analysis)
            if context_parts:
                parts.append(f"\nSupporting data:")
                parts.extend(f"  - {c}" for c in context_parts)

        return "\n".join(parts)

    def explain_judgment(self, judgment: dict[str, Any]) -> str:
        """Explain a JudgmentAdvisor verdict."""
        verdict = judgment.get("verdict", "unknown")
        risk = judgment.get("risk_score", 0)
        checks = judgment.get("checks", [])
        reason = judgment.get("reason", "")

        parts = [f"Judgment verdict: {verdict.upper()} (risk score: {risk:.0%})"]

        if reason:
            parts.append(f"Reason: {reason}")

        # Show individual checks
        concerning = [c for c in checks if c.get("risk", 0) > 0.3]
        if concerning:
            parts.append("\nConcerning factors:")
            for c in concerning:
                parts.append(f"  - {c['check']}: {c['reason']} (risk: {c['risk']:.0%})")

        recommendations = judgment.get("recommendations", [])
        if recommendations:
            parts.append("\nRecommendations:")
            for r in recommendations:
                parts.append(f"  - {r}")

        return "\n".join(parts)

    def summarize_situation(self, situation: dict[str, Any]) -> str:
        """Generate a plain-language store situation summary."""
        financial = situation.get("financial", {})
        inventory = situation.get("inventory", {})
        customers = situation.get("customers", {})
        health = situation.get("health", {})
        alerts = situation.get("alerts", [])

        parts = ["Store Situation Summary:"]

        # Financial
        revenue = financial.get("gross_revenue", 0)
        profit = financial.get("net_profit", 0)
        grade = financial.get("health_grade", health.get("overall_grade", "?"))
        if revenue:
            parts.append(f"  Revenue: ${revenue:,.2f} | Profit: ${profit:,.2f} | Health: {grade}")

        # Inventory
        total = inventory.get("total_products", 0)
        oos = inventory.get("out_of_stock_count", 0)
        low = inventory.get("low_stock_count", 0)
        if total:
            parts.append(f"  Inventory: {total} products | {oos} out of stock | {low} low stock")

        # Customers
        total_cust = customers.get("total", 0)
        churn = customers.get("churn_risk_pct", 0)
        if total_cust:
            parts.append(f"  Customers: {total_cust} total | {churn:.0f}% churn risk")

        # Alerts
        if alerts:
            parts.append(f"\n  Active alerts ({len(alerts)}):")
            for a in alerts[:5]:
                parts.append(f"    [{a.get('severity', '?').upper()}] {a.get('message', '?')}")

        return "\n".join(parts)

    def _goal_narrative(self, goal: str) -> str:
        """Convert goal ID to plain language."""
        narratives = {
            "maximize_profit": "Maximize profitability",
            "grow_customers": "Grow customer base and reduce churn",
            "increase_aov": "Increase average order value",
            "survive_crisis": "Stabilize — focus on cash flow and margins",
            "capture_opportunity": "Capture seasonal or trending opportunity",
        }
        return narratives.get(goal, goal.replace("_", " ").title())

    def _extract_analysis_context(self, analysis: dict[str, Any]) -> list[str]:
        """Extract key data points from analysis for the narrative."""
        context = []
        products = analysis.get("products", {})
        if isinstance(products, dict):
            viable = products.get("viable_count", 0)
            total = products.get("total", 0)
            if total:
                context.append(f"{viable}/{total} products are viable")

        customers = analysis.get("customers", {})
        if isinstance(customers, dict):
            churn = customers.get("churn_risk", 0)
            if churn:
                context.append(f"{churn} customers at churn risk")

        revenue = analysis.get("revenue", {})
        if isinstance(revenue, dict):
            growth = revenue.get("growth_pct", 0)
            if growth:
                context.append(f"Revenue trend: {growth:+.1f}%")

        return context
