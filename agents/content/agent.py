"""Content Agent — orchestrates Content Generation, SEO, and Visual engines.

This is the AGENT file. It ONLY orchestrates — delegates to:
  - planner.py → decides what to do
  - executor.py → calls engines
  - evaluator.py → assesses quality

Agent contract:
  Input:  {goal: str, context: {products, topics, content, ...}, constraints: {}}
  Output: {status, data: {plan, results, evaluation, recommendation}, meta: {agent, steps}, error}
"""
from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from .planner import create_plan
from .executor import execute_plan
from .evaluator import evaluate_results


class ContentAgent(BaseAgent):
    """Content Agent — generates descriptions, blog, images, video scripts.

    Combines Product Description, Content Generation, Search Optimization,
    Image Optimization, Video Marketing, and Tag Management engines
    to answer: "What content do we need and how good is it?"
    """

    def __init__(self) -> None:
        super().__init__(name="content_agent")

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
        """Generate final recommendation from combined content data."""
        score = evaluation.get("score", 0)
        quality = evaluation.get("quality", "low")

        engine_results = results.get("engine_results", {})
        pd = engine_results.get("product_description", {})
        cg = engine_results.get("content_generation", {})
        seo = engine_results.get("search_optimization", {})

        # Extract key findings
        findings = []

        # Product description findings
        if pd.get("status") == "success":
            pd_data = pd.get("data", {})
            if pd_data.get("descriptions"):
                findings.append(f"Generated {len(pd_data['descriptions'])} product descriptions")
            if pd_data.get("bullet_points"):
                findings.append("Bullet points created for product listings")

        # Content generation findings
        if cg.get("status") == "success":
            cg_data = cg.get("data", {})
            if cg_data.get("blog_posts"):
                findings.append(f"Generated {len(cg_data['blog_posts'])} blog posts")
            if cg_data.get("ad_copy"):
                findings.append("Ad copy created for campaigns")

        # SEO findings
        if seo.get("status") == "success":
            seo_data = seo.get("data", {})
            if seo_data.get("seo_analysis"):
                findings.append("SEO analysis completed")
            if seo_data.get("keywords"):
                findings.append(f"Identified {len(seo_data['keywords'])} target keywords")

        # Final recommendation
        if score >= 70 and quality == "high":
            action = "publish_content"
            confidence = "high"
            reason = "Content quality is high and SEO-ready for publication"
        elif score >= 50:
            action = "a_b_test_copy"
            confidence = "medium"
            reason = "Content is decent but should be A/B tested before full rollout"
        elif score >= 30:
            action = "revise_and_rewrite"
            confidence = "medium"
            reason = "Content needs revision to meet quality and SEO standards"
        else:
            action = "add_visual_content"
            confidence = "low"
            reason = "Content is thin — add visual assets and rewrite copy"

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
        if action == "publish_content":
            return [
                "Schedule content publication across channels",
                "Set up analytics tracking for each piece",
                "Monitor engagement and conversion rates",
                "Plan next content cycle based on performance",
            ]
        if action == "a_b_test_copy":
            return [
                "Create variant copies for A/B testing",
                "Set up split test infrastructure",
                "Run tests for minimum 7 days",
                "Select winning variants and publish",
            ]
        if action == "revise_and_rewrite":
            return [
                "Review SEO analysis for keyword gaps",
                "Rewrite underperforming copy sections",
                "Add missing product details and benefits",
                "Re-evaluate after revision",
            ]
        return [
            "Generate product images and alt text",
            "Create video scripts for key products",
            "Build visual content library",
            "Re-run content analysis with visual assets",
        ]
