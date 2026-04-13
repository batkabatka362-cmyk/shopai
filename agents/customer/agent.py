"""Customer Agent — orchestrates Customer Segmentation, Churn, and Sentiment engines.

This is the AGENT file. It ONLY orchestrates — delegates to:
  - planner.py → decides what to do
  - executor.py → calls engines
  - evaluator.py → assesses quality

Agent contract:
  Input:  {goal: str, context: {customers, orders, reviews, ...}, constraints: {}}
  Output: {status, data: {plan, results, evaluation, recommendation}, meta: {agent, steps}, error}
"""
from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from .planner import create_plan
from .executor import execute_plan
from .evaluator import evaluate_results


class CustomerAgent(BaseAgent):
    """Customer Agent — segments, retains, recovers, upsells customers.

    Combines Customer Segmentation, Churn Prediction, Sentiment Analysis,
    Review Management, Customer Support, Chatbot, and Audience Targeting
    engines to answer: "How do we maximize customer lifetime value?"
    """

    def __init__(self) -> None:
        super().__init__(name="customer_agent")

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
        """Generate final recommendation from combined customer data."""
        score = evaluation.get("score", 0)
        quality = evaluation.get("quality", "low")

        engine_results = results.get("engine_results", {})
        seg = engine_results.get("customer_segmentation", {})
        churn = engine_results.get("churn_prediction", {})
        sent = engine_results.get("sentiment_analysis", {})

        # Extract key findings
        findings = []

        # Segmentation findings
        if seg.get("status") == "success":
            seg_data = seg.get("data", {})
            if seg_data.get("segments"):
                findings.append(f"Identified {len(seg_data['segments'])} customer segments")
            if seg_data.get("rfm_analysis"):
                findings.append("RFM analysis completed")

        # Churn findings
        if churn.get("status") == "success":
            churn_data = churn.get("data", {})
            if churn_data.get("churn_risks"):
                risks = churn_data["churn_risks"]
                high_risk = [r for r in risks if isinstance(r, dict) and r.get("risk_level") == "high"] if isinstance(risks, list) else []
                findings.append(f"Churn risks: {len(high_risk)} high-risk customers identified")

        # Sentiment findings
        if sent.get("status") == "success":
            sent_data = sent.get("data", {})
            if sent_data.get("sentiment_scores"):
                findings.append("Sentiment analysis completed across reviews")

        # Final recommendation
        if score >= 70 and quality == "high":
            action = "send_retention_offers"
            confidence = "high"
            reason = "Customer data supports targeted retention campaigns"
        elif score >= 50:
            action = "launch_winback_campaign"
            confidence = "medium"
            reason = "Churn signals detected — winback campaign recommended"
        elif score >= 30:
            action = "upgrade_loyalty_tier"
            confidence = "medium"
            reason = "Loyal segments identified that could benefit from tier upgrades"
        else:
            action = "investigate_issues"
            confidence = "low"
            reason = "Insufficient data to determine customer strategy"

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
        if action == "send_retention_offers":
            return [
                "Create personalized offers for high-value segments",
                "Set up automated email sequences for at-risk customers",
                "A/B test retention messaging",
                "Monitor retention rates over 30 days",
            ]
        if action == "launch_winback_campaign":
            return [
                "Identify churned customers from last 90 days",
                "Design winback offer with progressive discounts",
                "Set up multi-channel outreach (email, SMS, ads)",
                "Track reactivation rate and ROI",
            ]
        if action == "upgrade_loyalty_tier":
            return [
                "Identify customers near tier thresholds",
                "Design tier upgrade incentives",
                "Communicate new benefits to eligible customers",
                "Monitor post-upgrade engagement",
            ]
        return [
            "Collect more customer feedback",
            "Review support ticket trends",
            "Analyze recent review sentiment",
            "Re-run customer analysis with updated data",
        ]
