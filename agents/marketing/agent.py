"""Marketing Agent — orchestrates campaign, content, ads, and social media engines.

This is the AGENT file. It ONLY orchestrates — delegates to:
  - planner.py → decides what to do
  - executor.py → calls engines
  - evaluator.py → assesses quality

Agent contract:
  Input:  {goal: str, context: {products, audiences, ...}, constraints: {}}
  Output: {status, data: {plan, results, evaluation, recommendation}, meta: {agent, steps}, error}
"""
from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from .planner import create_plan
from .executor import execute_plan
from .evaluator import evaluate_results


class MarketingAgent(BaseAgent):
    """Marketing Agent — creates campaigns, content, ads, and social media.

    Combines content generation, email marketing, social media, A/B testing,
    influencer, affiliate, landing page, and video engines to answer:
    "How do we reach customers and drive conversions?"
    """

    def __init__(self) -> None:
        super().__init__(name="marketing_agent")

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
        """Generate final recommendation from combined marketing analysis."""
        score = evaluation.get("score", 0)
        quality = evaluation.get("quality", "low")

        engine_results = results.get("engine_results", {})
        content = engine_results.get("content_generation", {})
        email = engine_results.get("email_marketing", {})
        social = engine_results.get("social_media", {})

        # Extract key findings
        findings = []

        if content.get("status") == "success":
            c_data = content.get("data", {})
            if c_data.get("marketing_copy"):
                findings.append("Marketing copy generated successfully")
            if c_data.get("ad_copy"):
                findings.append("Ad copy created for campaigns")

        if email.get("status") == "success":
            e_data = email.get("data", {})
            campaigns = e_data.get("email_campaigns", [])
            if campaigns:
                findings.append(f"Created {len(campaigns)} email campaigns")

        if social.get("status") == "success":
            s_data = social.get("data", {})
            posts = s_data.get("social_posts", [])
            if posts:
                findings.append(f"Generated {len(posts)} social media posts")

        # Final recommendation
        if score >= 70 and quality == "high":
            action = "launch_campaign"
            confidence = "high"
            reason = "Content, channels, and audience alignment all support launch"
        elif score >= 40:
            action = "revise_content"
            confidence = "medium"
            reason = "Campaign has potential but content or targeting needs work"
        else:
            action = "increase_budget"
            confidence = "low"
            reason = "Campaign coverage or content quality is too low for launch"

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
        if action == "launch_campaign":
            return [
                "Schedule email campaigns for optimal send times",
                "Publish social media posts across channels",
                "Activate A/B tests on landing pages",
                "Monitor initial performance metrics",
            ]
        if action == "revise_content":
            return [
                "Review and improve ad copy messaging",
                "Refine audience targeting segments",
                "Create additional content variations for testing",
                "Align messaging across all channels",
            ]
        return [
            "Evaluate budget allocation across channels",
            "Consider adding influencer or affiliate channels",
            "Expand content production capacity",
            "Research competitor marketing strategies",
        ]
