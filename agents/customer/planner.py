"""Customer Agent planner — decides which engines to use and in what order.

Thin wrapper around ``agents.base.planner.create_plan_base``.
"""
from __future__ import annotations

from typing import Any

from agents.base.planner import create_plan_base, wrap_engine_input


ENGINE_CAPABILITIES = {
    "customer_segmentation": {
        "provides": ["segments", "rfm_analysis"],
        "requires": ["customers", "orders"],
        "optional": ["demographics", "behavior_data"],
    },
    "churn_prediction": {
        "provides": ["churn_risks"],
        "requires": ["customers", "orders"],
        "optional": ["engagement_data", "support_history"],
    },
    "sentiment_analysis": {
        "provides": ["sentiment_scores"],
        "requires": ["reviews"],
        "optional": ["social_mentions", "support_tickets"],
    },
    "review_management": {
        "provides": ["review_actions"],
        "requires": ["reviews"],
        "optional": ["products", "response_templates"],
    },
    "customer_support": {
        "provides": ["support_intelligence"],
        "requires": ["tickets"],
        "optional": ["agents", "sla_config"],
    },
    "chatbot": {
        "provides": ["chat_responses"],
        "requires": ["queries"],
        "optional": ["knowledge_base", "product_catalog"],
    },
    "audience_targeting": {
        "provides": ["audiences"],
        "requires": ["segments"],
        "optional": ["campaign_goals", "budget"],
    },
}

GOAL_ENGINE_MAP = {
    "segment_customers": ["customer_segmentation"],
    "prevent_churn": ["customer_segmentation", "churn_prediction", "sentiment_analysis"],
    "recover_customers": ["customer_segmentation", "churn_prediction", "review_management"],
    "upsell_customers": ["customer_segmentation", "audience_targeting"],
    "full_customer_management": [
        "customer_segmentation", "churn_prediction", "sentiment_analysis",
        "review_management", "customer_support", "chatbot", "audience_targeting",
    ],
    "improve_support": ["customer_support", "chatbot", "sentiment_analysis"],
}

DEFAULT_ENGINES = ["customer_segmentation", "churn_prediction"]


def create_plan(goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Create an execution plan for the Customer Agent."""
    return create_plan_base(
        goal, context, constraints,
        engine_capabilities=ENGINE_CAPABILITIES,
        goal_engine_map=GOAL_ENGINE_MAP,
        default_engines=DEFAULT_ENGINES,
        build_engine_input=_build_engine_input,
        get_dependencies=_get_dependencies,
        determine_strategy=_determine_strategy,
    )


def _build_engine_input(engine_name: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Build the input payload for a specific engine."""
    customers = context.get("customers", [])
    orders = context.get("orders", [])

    if engine_name == "customer_segmentation":
        return wrap_engine_input({
            "customers": customers,
            "orders": orders,
            "demographics": context.get("demographics", {}),
            "behavior_data": context.get("behavior_data", {}),
        })

    if engine_name == "churn_prediction":
        return wrap_engine_input({
            "customers": customers,
            "orders": orders,
            "engagement_data": context.get("engagement_data", {}),
            "support_history": context.get("support_history", []),
        })

    if engine_name == "sentiment_analysis":
        return wrap_engine_input({
            "reviews": context.get("reviews", []),
            "social_mentions": context.get("social_mentions", []),
            "support_tickets": context.get("support_tickets", []),
        })

    if engine_name == "review_management":
        return wrap_engine_input({
            "reviews": context.get("reviews", []),
            "products": context.get("products", []),
            "response_templates": context.get("response_templates", []),
        })

    if engine_name == "customer_support":
        return wrap_engine_input({
            "tickets": context.get("tickets", []),
            "agents": context.get("agents", []),
            "sla_config": context.get("sla_config", {}),
        })

    if engine_name == "chatbot":
        return wrap_engine_input({
            "queries": context.get("queries", []),
            "knowledge_base": context.get("knowledge_base", {}),
            "product_catalog": context.get("product_catalog", []),
        })

    if engine_name == "audience_targeting":
        return wrap_engine_input({
            "segments": context.get("segments", []),
            "campaign_goals": context.get("campaign_goals", {}),
            "budget": context.get("budget", 0),
        })

    # Defensive fallback: never leak context. Pass 35.
    return wrap_engine_input({})


def _get_dependencies(engine_name: str, existing_steps: list[dict]) -> list[str]:
    """Determine which previous steps this engine depends on."""
    if engine_name == "churn_prediction" and any(s["name"] == "customer_segmentation" for s in existing_steps):
        return ["customer_segmentation"]
    if engine_name == "audience_targeting" and any(s["name"] == "customer_segmentation" for s in existing_steps):
        return ["customer_segmentation"]
    if engine_name == "review_management" and any(s["name"] == "sentiment_analysis" for s in existing_steps):
        return ["sentiment_analysis"]
    return []


def _determine_strategy(goal: str, context: dict[str, Any]) -> str:
    """Determine customer strategy."""
    if "quick" in goal or "fast" in goal:
        return "quick_scan"
    if "full" in goal or "thorough" in goal:
        return "full_management"
    if "churn" in goal or "retain" in goal:
        return "retention_focused"
    if "recover" in goal or "winback" in goal:
        return "recovery_focused"
    if "upsell" in goal or "cross" in goal:
        return "growth_focused"
    if "support" in goal:
        return "support_focused"
    return "balanced"
