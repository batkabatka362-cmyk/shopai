"""Research Agent — orchestrates Market Research + Trend Discovery engines.

This is the AGENT file. It ONLY orchestrates — delegates to:
  - planner.py → decides what to do
  - executor.py → calls engines
  - evaluator.py → assesses quality

Agent contract:
  Input:  {goal: str, context: {category, ...}, constraints: {}}
  Output: {status, data: {plan, results, evaluation, recommendation}, meta: {agent, steps}, error}

Phase 6 note: ``execute()`` now also queries the adapter
``SmartRouter`` for real web search hits when the dispatcher
has injected ``context["_router"]`` and the context carries a
research category or topic. Real SERP data supplements the
existing trend-discovery heuristics.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from agents.base import BaseAgent
from .planner import create_plan
from .executor import execute_plan
from .evaluator import evaluate_results

logger = get_logger("agent.research")


class ResearchAgent(BaseAgent):
    """Research Agent — finds market opportunities.

    Combines Market Research Engine + Trend Discovery Engine
    to answer: "Is this market worth entering?"
    """

    def __init__(self) -> None:
        super().__init__(name="research_agent")

    def plan(self, goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
        """Delegate planning to planner module."""
        return create_plan(goal, context, constraints)

    def execute(self, plan: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Delegate execution to executor module, then augment
        with real web search hits via the adapter SmartRouter
        when available."""
        results = execute_plan(plan, context)
        if not isinstance(results, dict):
            results = {}
        augmentation = self._augment_with_web_search(context)
        if augmentation is not None:
            results.setdefault("adapter_augmentations", {})
            results["adapter_augmentations"]["web_search"] = augmentation
        return results

    def _augment_with_web_search(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Run a real web search for the context's research
        topic via the router.

        Returns ``None`` when the router isn't available, no
        search adapter is configured, or the context doesn't
        carry a topic. The existing engine pipeline already
        ran; this augmentation is additive.
        """
        router = context.get("_router") if isinstance(context, dict) else None
        if router is None:
            return None

        # Pick the topic/category/query the context already
        # carries. ResearchAgent is commonly invoked with a
        # ``category`` field ("electronics", "fitness", ...);
        # fall back to an explicit ``query`` when present.
        query = ""
        if isinstance(context, dict):
            query = (
                context.get("query")
                or context.get("research_query")
                or context.get("category")
                or context.get("topic")
                or ""
            )
        query = str(query).strip()
        if not query:
            return None

        try:
            from core.adapters import Capability
        except Exception:  # noqa: BLE001
            return None

        try:
            result = router.execute(
                Capability.WEB_SEARCH,
                {"query": query, "max_results": 5},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("web search augmentation raised: %s", exc)
            return None

        if not result.ok:
            return None

        data = result.data or {}
        hits = data.get("hits") or []
        return {
            "adapter": result.adapter,
            "query": query,
            "hit_count": len(hits),
            # Only surface the top 3 titles + urls so the
            # recommender doesn't drown in a full SERP.
            "top_hits": [
                {"title": h.get("title", ""), "url": h.get("url", "")}
                for h in hits[:3]
                if isinstance(h, dict)
            ],
        }

    def evaluate(self, results: dict[str, Any], goal: str) -> dict[str, Any]:
        """Delegate evaluation to evaluator module."""
        return evaluate_results(results, goal)

    def recommend(self, results: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
        """Generate final recommendation from combined research."""
        score = evaluation.get("score", 0)
        quality = evaluation.get("quality", "low")

        engine_results = results.get("engine_results", {})
        mr = engine_results.get("market_research", {})
        td = engine_results.get("trend_discovery", {})

        # Extract key findings
        findings = []

        # Market Research findings
        if mr.get("status") == "success":
            mr_data = mr.get("data", {})
            verdict = mr_data.get("verdict", {})
            if isinstance(verdict, dict):
                findings.append(f"Market verdict: {verdict.get('verdict', '?')} (score {verdict.get('score', 0)})")
            summary = mr_data.get("summary", "")
            if summary:
                findings.append(summary[:200])

        # Trend Discovery findings
        if td.get("status") == "success":
            td_data = td.get("data", {})
            if td_data.get("composite_score"):
                findings.append(f"Trend score: {td_data['composite_score']}")

        # Final recommendation
        if score >= 70 and quality == "high":
            action = "proceed_to_product_selection"
            confidence = "high"
            reason = "Market research and trend analysis both support opportunity"
        elif score >= 50:
            action = "gather_more_data"
            confidence = "medium"
            reason = "Some positive signals but need more data to confirm"
        else:
            action = "consider_alternatives"
            confidence = "low"
            reason = "Insufficient evidence of viable opportunity"

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
        if action == "proceed_to_product_selection":
            return [
                "Run Product Selection engine to find specific products",
                "Run Profitability Calculator on top candidates",
                "Run Competition Analyzer on shortlist",
                "Begin supplier research",
            ]
        if action == "gather_more_data":
            return [
                "Collect more keyword data (Google Keyword Planner)",
                "Analyze competitor reviews (Amazon, Shopify stores)",
                "Check social media trends (TikTok, Instagram)",
                "Re-run research in 2 weeks with new data",
            ]
        return [
            "Evaluate alternative categories",
            "Broaden or narrow the niche",
            "Consider adjacent markets",
        ]
