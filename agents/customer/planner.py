"""Customer Agent planner — decides which engines to use and in what order.

Planning logic:
  1. Customer Segmentation for baseline understanding
  2. Churn Prediction to identify at-risk customers
  3. Sentiment Analysis for qualitative signals
  4. Review Management for feedback loops
  5. Customer Support for service intelligence
  6. Chatbot for automated interactions
  7. Audience Targeting for campaign delivery

If goal is specific:
  - "segment_customers" → Customer Segmentation only
  - "prevent_churn" → Segmentation + Churn + Sentiment
  - "recover_customers" → Segmentation + Churn + Review Management
  - "full_customer_management" → all engines
"""
from __future__ import annotations

from typing import Any


# Engine capabilities mapping
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

# Goal → engine mapping
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


def create_plan(goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Create an execution plan for the Customer Agent.

    Returns list of engines to call, in order, with their inputs.
    """
    # Defensive: coerce caller args. Audit pass 35.
    goal = goal if isinstance(goal, str) else ""
    context = context if isinstance(context, dict) else {}
    constraints = constraints if isinstance(constraints, dict) else {}

    goal_lower = goal.lower().replace(" ", "_")
    engines_needed = _select_engines(goal_lower, context)

    # Build engine input for each
    steps = []
    for engine_name in engines_needed:
        engine_input = _build_engine_input(engine_name, context, constraints)
        steps.append({
            "name": engine_name,
            "purpose": _engine_purpose(engine_name),
            "input": engine_input,
            "depends_on": _get_dependencies(engine_name, steps),
        })

    # Determine strategy
    strategy = _determine_strategy(goal_lower, context)

    return {
        "engines": steps,
        "strategy": strategy,
        "estimated_steps": len(steps),
        "goal": goal,
    }


def _select_engines(goal: str, context: dict[str, Any]) -> list[str]:
    """Select which engines to use based on goal."""
    # Check goal mapping
    for key, engines in GOAL_ENGINE_MAP.items():
        if key in goal:
            return engines

    # Default: segmentation + churn
    return ["customer_segmentation", "churn_prediction"]


def _build_engine_input(engine_name: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Build the input payload for a specific engine."""
    customers = context.get("customers", [])
    orders = context.get("orders", [])

    if engine_name == "customer_segmentation":
        return {
            "status": "success",
            "data": {
                "customers": customers,
                "orders": orders,
                "demographics": context.get("demographics", {}),
                "behavior_data": context.get("behavior_data", {}),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "churn_prediction":
        return {
            "status": "success",
            "data": {
                "customers": customers,
                "orders": orders,
                "engagement_data": context.get("engagement_data", {}),
                "support_history": context.get("support_history", []),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "sentiment_analysis":
        return {
            "status": "success",
            "data": {
                "reviews": context.get("reviews", []),
                "social_mentions": context.get("social_mentions", []),
                "support_tickets": context.get("support_tickets", []),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "review_management":
        return {
            "status": "success",
            "data": {
                "reviews": context.get("reviews", []),
                "products": context.get("products", []),
                "response_templates": context.get("response_templates", []),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "customer_support":
        return {
            "status": "success",
            "data": {
                "tickets": context.get("tickets", []),
                "agents": context.get("agents", []),
                "sla_config": context.get("sla_config", {}),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "chatbot":
        return {
            "status": "success",
            "data": {
                "queries": context.get("queries", []),
                "knowledge_base": context.get("knowledge_base", {}),
                "product_catalog": context.get("product_catalog", []),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "audience_targeting":
        return {
            "status": "success",
            "data": {
                "segments": context.get("segments", []),
                "campaign_goals": context.get("campaign_goals", {}),
                "budget": context.get("budget", 0),
            },
            "meta": {},
            "error": None,
        }

    # Defensive: never leak the entire caller context dict
    # downstream when an engine name isn't recognised. Audit
    # pass 35.
    return {"status": "success", "data": {}, "meta": {}, "error": None}


def _engine_purpose(engine_name: str) -> str:
    """Safe lookup for an engine's primary purpose string."""
    cap = ENGINE_CAPABILITIES.get(engine_name) or {}
    provides = cap.get("provides") or []
    return provides[0] if provides else "unknown"


def _get_dependencies(engine_name: str, existing_steps: list[dict]) -> list[str]:
    """Determine which previous steps this engine depends on."""
    # Churn prediction can use segmentation results
    if engine_name == "churn_prediction" and any(s["name"] == "customer_segmentation" for s in existing_steps):
        return ["customer_segmentation"]
    # Audience targeting needs segments
    if engine_name == "audience_targeting" and any(s["name"] == "customer_segmentation" for s in existing_steps):
        return ["customer_segmentation"]
    # Review management can use sentiment
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
