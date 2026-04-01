"""Research Agent planner — decides which engines to use and in what order.

Planning logic:
  1. Always start with Market Research (understand the market)
  2. Then Trend Discovery (find opportunities within the market)
  3. Combine results for final recommendation

If goal is specific:
  - "find trending products" → Trend Discovery first
  - "evaluate market size" → Market Research only
  - "full research" → both engines, full pipeline
"""
from __future__ import annotations

from typing import Any


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


def create_plan(goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Create an execution plan for the Research Agent.

    Returns list of engines to call, in order, with their inputs.
    """
    # Determine which engines to use
    goal_lower = goal.lower().replace(" ", "_")
    engines_needed = _select_engines(goal_lower, context)

    # Build engine input for each
    steps = []
    for engine_name in engines_needed:
        engine_input = _build_engine_input(engine_name, context, constraints)
        steps.append({
            "name": engine_name,
            "purpose": ENGINE_CAPABILITIES[engine_name]["provides"][0],
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

    # Default: full research
    return ["market_research", "trend_discovery"]


def _build_engine_input(engine_name: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Build the input payload for a specific engine."""
    category = context.get("category", "")

    if engine_name == "market_research":
        return {
            "status": "success",
            "data": {
                "category": category,
                "products": context.get("products", []),
                "competitors": context.get("competitors", []),
                "search_data": context.get("search_data", {}),
                "pricing": context.get("pricing", {}),
                "reviews": context.get("reviews", []),
                "trend_signals": context.get("trend_signals", {}),
                "sub_niche_pct": context.get("sub_niche_pct", 0.1),
                "store_maturity": context.get("store_maturity", "new_store"),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "trend_discovery":
        return {
            "status": "success",
            "data": {
                "category": category,
                "keywords": context.get("keywords", []),
                "trend_signals": context.get("trend_signals", {}),
                "social_data": context.get("social_data", {}),
                "marketplace_data": context.get("marketplace_data", {}),
            },
            "meta": {},
            "error": None,
        }

    return {"status": "success", "data": context, "meta": {}, "error": None}


def _get_dependencies(engine_name: str, existing_steps: list[dict]) -> list[str]:
    """Determine which previous steps this engine depends on."""
    # Trend discovery can use market research results
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
