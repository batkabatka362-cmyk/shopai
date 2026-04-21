"""Marketing Agent — orchestrates campaign, content, ads, and social media engines.

This is the AGENT file. It ONLY orchestrates — delegates to:
  - planner.py → decides what to do
  - executor.py → calls engines
  - evaluator.py → assesses quality

Agent contract:
  Input:  {goal: str, context: {products, audiences, ...}, constraints: {}}
  Output: {status, data: {plan, results, evaluation, recommendation}, meta: {agent, steps}, error}

Phase 6 note: ``execute()`` now also queries the adapter
``SmartRouter`` for LLM-generated marketing copy when the
dispatcher has injected ``context["_router"]`` and the goal
mentions a product or campaign context. Real copy supplements
the existing template-based content engine output.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from agents.base import BaseAgent
from .planner import create_plan
from .executor import execute_plan
from .evaluator import evaluate_results

logger = get_logger("agent.marketing")

_COPY_SYSTEM_PROMPT = (
    "You are a direct-response e-commerce copywriter. Given a "
    "product or campaign context, produce ONE compelling subject "
    "line (<=60 chars) and ONE 2-sentence body. Be concrete, "
    "specific, and honest — do NOT invent prices, discounts, or "
    "features the context doesn't mention."
)


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
        """Delegate execution to executor module, then augment
        with LLM-generated marketing copy via the adapter
        SmartRouter when available."""
        results = execute_plan(plan, context)
        if not isinstance(results, dict):
            results = {}
        augmentation = self._augment_with_llm_copy(context)
        if augmentation is not None:
            results.setdefault("adapter_augmentations", {})
            results["adapter_augmentations"]["copy_generation"] = augmentation
        return results

    def _augment_with_llm_copy(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Ask the router for a piece of LLM-generated copy
        grounded in the caller's product / campaign context.

        Scope: this is intentionally NOT a send-email call —
        the marketing agent should not dispatch customer-facing
        messages during the orchestration phase. Copy
        generation is a safe augmentation that gives the
        recommender extra material without touching any
        external delivery channel. The SEND_EMAIL capability
        is reserved for a later execution phase.
        """
        router = context.get("_router") if isinstance(context, dict) else None
        if router is None:
            return None

        # Build a short prompt from whatever product / campaign
        # data the context happens to carry. If nothing useful
        # is present, skip the augmentation silently.
        product_hint = ""
        if isinstance(context, dict):
            products = context.get("products") or []
            if isinstance(products, list) and products:
                first = products[0] if isinstance(products[0], dict) else {}
                name = first.get("name") or first.get("title") or ""
                price = first.get("price")
                if name:
                    product_hint = f"Product: {name}"
                    if price:
                        product_hint += f" (price: ${price})"

        campaign_hint = ""
        if isinstance(context, dict):
            goal_ctx = context.get("campaign_goal") or context.get("goal")
            if goal_ctx:
                campaign_hint = f"Campaign goal: {goal_ctx}"

        if not product_hint and not campaign_hint:
            return None

        prompt_lines = [
            "Write marketing email copy grounded in:",
            product_hint,
            campaign_hint,
        ]
        prompt = "\n".join(line for line in prompt_lines if line)

        try:
            from core.adapters import Capability
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "marketing copy augmentation unavailable — "
                "core.adapters import failed: %s",
                exc,
            )
            return None

        try:
            result = router.execute(
                Capability.CHAT_COMPLETE,
                {
                    "prompt": prompt,
                    "system": _COPY_SYSTEM_PROMPT,
                    "max_tokens": 200,
                    "temperature": 0.4,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "marketing copy augmentation raised: %s", exc,
            )
            return None

        if not result.ok:
            logger.warning(
                "marketing copy augmentation: router returned "
                "not-ok (adapter=%s error=%s)",
                getattr(result, "adapter", "?"),
                getattr(result, "error", ""),
            )
            return None

        data = result.data or {}
        text = str(data.get("text", "") or "").strip()
        if not text:
            logger.warning(
                "marketing copy augmentation: adapter=%s "
                "returned empty text",
                getattr(result, "adapter", "?"),
            )
            return None
        return {
            "adapter": result.adapter,
            "model": result.model,
            "copy": text,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
        }

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
