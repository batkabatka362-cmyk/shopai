"""Product Agent planner — decides which engines to use and in what order.

Thin wrapper around ``agents.base.planner.create_plan_base``.
"""
from __future__ import annotations

from typing import Any

from agents.base.planner import create_plan_base, wrap_engine_input


ENGINE_CAPABILITIES = {
    "product_filter": {
        "provides": ["filtered_products"],
        "requires": ["products", "criteria"],
        "optional": ["category", "price_range"],
    },
    "product_scoring": {
        "provides": ["scored_products"],
        "requires": ["products"],
        "optional": ["scoring_weights", "market_data"],
    },
    "product_validation": {
        "provides": ["validated_products"],
        "requires": ["products"],
        "optional": ["risk_thresholds", "market_data"],
    },
    "product_ranking": {
        "provides": ["ranked_products"],
        "requires": ["scored_products"],
        "optional": ["ranking_strategy"],
    },
    "pricing": {
        "provides": ["price_recommendations"],
        "requires": ["products", "market_data"],
        "optional": ["competitor_prices", "margins"],
    },
    "profitability_calculator": {
        "provides": ["profitability"],
        "requires": ["products", "costs"],
        "optional": ["shipping_costs", "tax_rates"],
    },
    "catalog": {
        "provides": ["catalog_updates"],
        "requires": ["products"],
        "optional": ["descriptions", "images"],
    },
}

GOAL_ENGINE_MAP = {
    "find_products": ["product_filter", "product_scoring", "product_ranking"],
    "validate_products": ["product_validation", "product_risk"],
    "price_products": ["pricing", "profitability_calculator"],
    "launch_product": ["product_filter", "product_scoring", "product_validation", "pricing", "catalog"],
    "optimize_catalog": ["product_ranking", "catalog"],
}

DEFAULT_ENGINES = ["product_filter", "product_scoring", "product_ranking"]


def create_plan(goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Create an execution plan for the Product Agent."""
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
    products = context.get("products", [])
    criteria = context.get("criteria", {})
    market_data = context.get("market_data", {})
    costs = context.get("costs", {})

    if engine_name == "product_filter":
        return wrap_engine_input({
            "products": products,
            "criteria": criteria,
            "category": context.get("category", ""),
            "price_range": context.get("price_range", {}),
        })

    if engine_name == "product_scoring":
        return wrap_engine_input({
            "products": products,
            "scoring_weights": context.get("scoring_weights", {}),
            "market_data": market_data,
        })

    if engine_name == "product_validation":
        return wrap_engine_input({
            "products": products,
            "risk_thresholds": context.get("risk_thresholds", {}),
            "market_data": market_data,
        })

    if engine_name == "product_ranking":
        return wrap_engine_input({
            "scored_products": context.get("scored_products", products),
            "ranking_strategy": context.get("ranking_strategy", "score_desc"),
        })

    if engine_name == "pricing":
        return wrap_engine_input({
            "products": products,
            "market_data": market_data,
            "competitor_prices": context.get("competitor_prices", {}),
            "margins": context.get("margins", {}),
        })

    if engine_name == "profitability_calculator":
        return wrap_engine_input({
            "products": products,
            "costs": costs,
            "shipping_costs": context.get("shipping_costs", {}),
            "tax_rates": context.get("tax_rates", {}),
        })

    if engine_name == "catalog":
        return wrap_engine_input({
            "products": products,
            "descriptions": context.get("descriptions", {}),
            "images": context.get("images", {}),
        })

    # Defensive fallback: never leak context. Pass 35.
    return wrap_engine_input({})


def _get_dependencies(engine_name: str, existing_steps: list[dict]) -> list[str]:
    """Determine which previous steps this engine depends on."""
    if engine_name == "product_ranking" and any(s["name"] == "product_scoring" for s in existing_steps):
        return ["product_scoring"]
    if engine_name == "pricing" and any(s["name"] == "product_filter" for s in existing_steps):
        return ["product_filter"]
    if engine_name == "catalog" and any(s["name"] == "pricing" for s in existing_steps):
        return ["pricing"]
    if engine_name == "profitability_calculator" and any(s["name"] == "pricing" for s in existing_steps):
        return ["pricing"]
    return []


def _determine_strategy(goal: str, context: dict[str, Any]) -> str:
    """Determine product strategy."""
    if "quick" in goal or "fast" in goal:
        return "quick_scan"
    if "launch" in goal:
        return "full_launch"
    if "price" in goal:
        return "pricing_focused"
    if "validate" in goal:
        return "validation_focused"
    if "catalog" in goal or "optimize" in goal:
        return "catalog_optimization"
    return "balanced"
