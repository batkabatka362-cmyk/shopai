"""Research Agent planner — decides which engines to use and in what order.

Thin wrapper around ``agents.base.planner.create_plan_base``.
Only the domain knowledge (which engines exist, which goal
substrings select which engines, how each engine's input
payload is built) lives here. The defensive coercion, step
assembly, and return shape live in the shared base.
"""
from __future__ import annotations

from typing import Any

from agents.base.planner import create_plan_base, wrap_engine_input


# Engine capabilities mapping
ENGINE_CAPABILITIES = {
    "market_research": {
        "provides": ["market_size", "trends", "seasonality", "gaps", "saturation"],
        "requires": ["category"],
        "optional": ["products", "competitors", "search_data", "pricing"],
    },
    "trend_discovery": {
        "provides": ["search_trends", "social_trends", "marketplace_trends", "emerging_niches", "trend_scores"],
        "requires": ["category"],
        "optional": ["keywords", "trend_signals", "social_data", "marketplace_data"],
    },
}

# Goal → engine mapping
GOAL_ENGINE_MAP = {
    "full_research": ["market_research", "trend_discovery"],
    "market_analysis": ["market_research"],
    "find_trends": ["trend_discovery"],
    "find_products": ["market_research", "trend_discovery"],
    "evaluate_category": ["market_research"],
    "find_opportunities": ["market_research", "trend_discovery"],
}

DEFAULT_ENGINES = ["market_research", "trend_discovery"]


def create_plan(goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Create an execution plan for the Research Agent."""
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
    category = context.get("category", "")

    if engine_name == "market_research":
        return wrap_engine_input({
            "category": category,
            "products": context.get("products", []),
            "competitors": context.get("competitors", []),
            "search_data": context.get("search_data", {}),
            "pricing": context.get("pricing", {}),
            "reviews": context.get("reviews", []),
            "trend_signals": context.get("trend_signals", {}),
            "sub_niche_pct": context.get("sub_niche_pct", 0.1),
            "store_maturity": context.get("store_maturity", "new_store"),
        })

    if engine_name == "trend_discovery":
        return wrap_engine_input({
            "category": category,
            "keywords": context.get("keywords", []),
            "trend_signals": context.get("trend_signals", {}),
            "social_data": context.get("social_data", {}),
            "marketplace_data": context.get("marketplace_data", {}),
        })

    # Defensive fallback: never leak the entire context bag to
    # an unknown engine name. Pass 35 security fix.
    return wrap_engine_input({})


def _get_dependencies(engine_name: str, existing_steps: list[dict]) -> list[str]:
    """Determine which previous steps this engine depends on."""
    if engine_name == "trend_discovery" and any(s["name"] == "market_research" for s in existing_steps):
        return ["market_research"]
    return []


def _determine_strategy(goal: str, context: dict[str, Any]) -> str:
    """Determine research strategy."""
    if "quick" in goal or "fast" in goal:
        return "quick_scan"
    if "deep" in goal or "thorough" in goal:
        return "deep_research"
    if "trend" in goal:
        return "trend_focused"
    if "market" in goal or "size" in goal:
        return "market_focused"
    return "balanced"
