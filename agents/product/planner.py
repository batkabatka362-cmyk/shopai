"""Product Agent planner — decides which engines to use and in what order.

Planning logic:
  1. Start with product filtering (narrow the pool)
  2. Score and rank (identify winners)
  3. Validate (check risk)
  4. Price (set optimal prices)
  5. Catalog (publish)

If goal is specific:
  - "find_products" → filter, score, rank
  - "validate_products" → validation + risk
  - "price_products" → pricing + profitability
  - "launch_product" → full pipeline
  - "optimize_catalog" → ranking + catalog
"""
from __future__ import annotations

from typing import Any


# Engine capabilities mapping
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

# Goal → engine mapping
GOAL_ENGINE_MAP = {
    "find_products": ["product_filter", "product_scoring", "product_ranking"],
    "validate_products": ["product_validation", "product_risk"],
    "price_products": ["pricing", "profitability_calculator"],
    "launch_product": ["product_filter", "product_scoring", "product_validation", "pricing", "catalog"],
    "optimize_catalog": ["product_ranking", "catalog"],
}


def create_plan(goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Create an execution plan for the Product Agent.

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
            "purpose": ENGINE_CAPABILITIES.get(engine_name, {}).get("provides", ["unknown"])[0],
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
    for key, engines in GOAL_ENGINE_MAP.items():
        if key in goal:
            return engines

    # Default: full product discovery pipeline
    return ["product_filter", "product_scoring", "product_ranking"]


def _build_engine_input(engine_name: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Build the input payload for a specific engine."""
    products = context.get("products", [])
    criteria = context.get("criteria", {})
    market_data = context.get("market_data", {})
    costs = context.get("costs", {})

    if engine_name == "product_filter":
        return {
            "status": "success",
            "data": {
                "products": products,
                "criteria": criteria,
                "category": context.get("category", ""),
                "price_range": context.get("price_range", {}),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "product_scoring":
        return {
            "status": "success",
            "data": {
                "products": products,
                "scoring_weights": context.get("scoring_weights", {}),
                "market_data": market_data,
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "product_validation":
        return {
            "status": "success",
            "data": {
                "products": products,
                "risk_thresholds": context.get("risk_thresholds", {}),
                "market_data": market_data,
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "product_ranking":
        return {
            "status": "success",
            "data": {
                "scored_products": context.get("scored_products", products),
                "ranking_strategy": context.get("ranking_strategy", "score_desc"),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "pricing":
        return {
            "status": "success",
            "data": {
                "products": products,
                "market_data": market_data,
                "competitor_prices": context.get("competitor_prices", {}),
                "margins": context.get("margins", {}),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "profitability_calculator":
        return {
            "status": "success",
            "data": {
                "products": products,
                "costs": costs,
                "shipping_costs": context.get("shipping_costs", {}),
                "tax_rates": context.get("tax_rates", {}),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "catalog":
        return {
            "status": "success",
            "data": {
                "products": products,
                "descriptions": context.get("descriptions", {}),
                "images": context.get("images", {}),
            },
            "meta": {},
            "error": None,
        }

    # Fallback for engines like product_risk
    return {"status": "success", "data": context, "meta": {}, "error": None}


def _get_dependencies(engine_name: str, existing_steps: list[dict]) -> list[str]:
    """Determine which previous steps this engine depends on."""
    # Product ranking depends on scoring
    if engine_name == "product_ranking" and any(s["name"] == "product_scoring" for s in existing_steps):
        return ["product_scoring"]
    # Pricing depends on filtering/validation
    if engine_name == "pricing" and any(s["name"] == "product_filter" for s in existing_steps):
        return ["product_filter"]
    # Catalog depends on pricing
    if engine_name == "catalog" and any(s["name"] == "pricing" for s in existing_steps):
        return ["pricing"]
    # Profitability depends on pricing
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
