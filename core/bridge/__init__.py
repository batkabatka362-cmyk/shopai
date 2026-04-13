"""AgentEngineBridge — connects agents to engines for intelligent orchestration.

Each agent specializes in a domain and manages its engines:
  - ProductAgent → manages product_selection, pricing, inventory engines
  - MarketingAgent → manages marketing, campaign, email, social engines
  - CustomerAgent → manages segmentation, churn, retention, loyalty engines
  - OperationsAgent → manages shipping, fulfillment, warehouse engines
  - AnalyticsAgent → manages analytics, forecasting, kpi engines
  - ContentAgent → manages content, seo, blog, description engines

Agents decide WHAT to run, engines do the WORK.
"""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id
from engines.registry import get_engine, is_registered
from engines.base.engine_types import EngineInput, EngineStatus, normalize_engine_output
from agents.communication.message_bus import MessageBus
from agents.communication.protocol import Protocol

logger = get_logger("bridge.agent_engine")


class AgentSpec:
    """Specification for a domain agent."""

    def __init__(self, name: str, engines: list[str], description: str = "") -> None:
        self.name = name
        self.engines = engines
        self.description = description


# Agent definitions — each agent owns a set of engines
AGENT_SPECS = {
    "product_agent": AgentSpec("product_agent", [
        "product_selection", "product_scoring", "product_validation", "product_ranking",
        "product_lifecycle", "product_optimization", "product_description", "product_comparison",
        "catalog", "pricing", "dynamic_pricing", "discount_strategy", "bundle", "upsell", "cross_sell",
    ], "Manages product selection, pricing, and catalog optimization"),

    "marketing_agent": AgentSpec("marketing_agent", [
        "marketing", "campaign", "email_marketing", "social_media", "ads", "influencer",
        "affiliate", "content_generation", "creative_generation", "ad_copy", "copywriting",
        "headline_generator", "audience_targeting", "landing_page", "ab_testing",
    ], "Manages marketing campaigns, content, and advertising"),

    "customer_agent": AgentSpec("customer_agent", [
        "customer_segmentation", "churn_prediction", "retention", "loyalty", "loyalty_program",
        "personalization", "recommendation", "sentiment_analysis", "review_management",
        "customer_support", "chatbot", "customer_journey", "ltv_prediction", "nps_tracking",
    ], "Manages customer relationships, segmentation, and retention"),

    "operations_agent": AgentSpec("operations_agent", [
        "inventory", "shipping_optimization", "delivery_optimization", "warehouse_optimization",
        "order_management", "order_routing", "fulfillment_optimization", "supply_chain",
        "logistics", "procurement", "returns_management", "refund_processing", "stock_prediction",
    ], "Manages inventory, fulfillment, and supply chain"),

    "analytics_agent": AgentSpec("analytics_agent", [
        "analytics", "forecasting", "kpi_tracking", "anomaly_detection", "trend_detection",
        "demand_forecasting", "revenue_forecasting", "cohort_analysis", "attribution",
        "predictive_analytics", "conversion_tracking", "financial", "margin_analysis",
    ], "Manages analytics, forecasting, and business intelligence"),

    "content_agent": AgentSpec("content_agent", [
        "seo", "blog_generation", "faq_generation", "translation", "keyword_research",
        "content_optimization", "search_optimization", "link_building", "product_description",
        "storytelling", "brand_voice", "video_marketing", "image_optimization",
    ], "Manages content creation, SEO, and optimization"),
}


class AgentEngineBridge:
    """Connects agents to engines — agents decide, engines execute."""

    def __init__(self) -> None:
        self._bus = MessageBus()
        self._protocol = Protocol()
        self._execution_log: list[dict[str, Any]] = []

    def get_agent_for_engine(self, engine_name: str) -> str | None:
        """Find which agent owns this engine."""
        for agent_name, spec in AGENT_SPECS.items():
            if engine_name in spec.engines:
                return agent_name
        return None

    def get_agent_engines(self, agent_name: str) -> list[str]:
        """Get all engines owned by an agent."""
        spec = AGENT_SPECS.get(agent_name)
        return spec.engines if spec else []

    def agent_run(self, agent_name: str, task: str, data: dict[str, Any]) -> dict[str, Any]:
        """Agent decides which engine(s) to run and coordinates execution."""
        spec = AGENT_SPECS.get(agent_name)
        if spec is None:
            return {"error": f"Unknown agent: {agent_name}"}

        run_id = generate_id("arun")
        start = time.monotonic()

        # Agent decides which engine to use based on task
        engine_name = self._select_engine(spec, task, data)
        if engine_name is None:
            return {"agent": agent_name, "error": "No suitable engine found for task"}

        # Agent publishes intent
        self._bus.publish("agent.intent", {
            "agent": agent_name, "engine": engine_name, "task": task, "run_id": run_id,
        }, sender=agent_name)

        # Execute engine
        result = self._execute_engine(engine_name, data, run_id)

        # Agent evaluates result and may chain to another engine
        follow_up = self._evaluate_and_chain(spec, result, data)
        if follow_up:
            result["follow_up"] = follow_up

        elapsed = time.monotonic() - start
        entry = {
            "run_id": run_id,
            "agent": agent_name,
            "engine": engine_name,
            "status": result.get("status", "unknown"),
            "elapsed": round(elapsed, 3),
            "follow_up": follow_up.get("engine") if follow_up else None,
        }
        self._execution_log.append(entry)

        result["_agent"] = {"name": agent_name, "engine": engine_name, "run_id": run_id, "elapsed": elapsed}
        return result

    def agent_multi_run(self, agent_name: str, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Agent runs multiple tasks in sequence, passing context between them."""
        results = []
        accumulated_context = {}
        for task in tasks:
            task_data = copy.deepcopy(task.get("data", {}))
            task_data.update(accumulated_context)
            result = self.agent_run(agent_name, task.get("task", ""), task_data)
            results.append(result)
            # Accumulate outputs for next task
            engine_result = result.get("result", {})
            if isinstance(engine_result, dict):
                for k, v in engine_result.items():
                    if not k.startswith("_"):
                        accumulated_context[k] = v
        return results

    def list_agents(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "engines": len(spec.engines), "description": spec.description}
            for name, spec in AGENT_SPECS.items()
        ]

    def get_execution_log(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._execution_log[-limit:])

    def _select_engine(self, spec: AgentSpec, task: str, data: dict[str, Any]) -> str | None:
        """Agent intelligence: select best engine for the task."""
        task_lower = task.lower()

        # Direct match by task name
        for engine in spec.engines:
            if engine == task_lower or engine.replace("_", " ") == task_lower:
                if is_registered(engine):
                    return engine

        # Keyword match
        for engine in spec.engines:
            if any(word in task_lower for word in engine.split("_")):
                if is_registered(engine):
                    return engine

        # Fallback: first available engine
        for engine in spec.engines:
            if is_registered(engine):
                return engine

        return None

    def _execute_engine(self, engine_name: str, data: dict[str, Any], run_id: str) -> dict[str, Any]:
        """Execute an engine and return structured result."""
        try:
            engine = get_engine(engine_name)
            inp = EngineInput(task_id=run_id, engine_name=engine_name, data=copy.deepcopy(data))
            # Try dict input (new engines), fall back to EngineInput (legacy)
            dict_input = {"status": "success", "data": copy.deepcopy(data), "meta": {}, "error": None}
            try:
                raw_output = engine.run(dict_input)
            except (TypeError, AttributeError):
                raw_output = engine.run(inp)
            output = normalize_engine_output(raw_output, inp)
            return {
                "status": output.status.value,
                "engine": engine_name,
                "result": output.result,
                "error": output.error,
            }
        except Exception as exc:
            return {"status": "error", "engine": engine_name, "result": {}, "error": str(exc)}

    def _evaluate_and_chain(self, spec: AgentSpec, result: dict, data: dict) -> dict[str, Any] | None:
        """Agent evaluates result and suggests follow-up engine if needed."""
        if result.get("status") != "completed":
            return None

        engine_result = result.get("result", {})
        intel = engine_result.get("_intelligence", {})
        related = intel.get("related_engines", [])

        # Check if any related engine is owned by this agent
        for eng in related:
            if eng in spec.engines and is_registered(eng):
                return {"engine": eng, "reason": f"Recommended follow-up from {result.get('engine')}"}

        return None
