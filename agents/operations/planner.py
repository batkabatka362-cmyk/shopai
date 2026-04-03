"""Operations Agent planner — decides which engines to use and in what order.

Planning logic:
  1. Inventory engine to assess current stock health
  2. Stock prediction for demand forecasting
  3. Supplier engine for sourcing decisions
  4. Shipping optimization for fulfillment
  5. Returns management for reverse logistics

If goal is specific:
  - "manage_inventory" → Inventory + Stock Prediction
  - "optimize_shipping" → Shipping Optimization + Inventory
  - "evaluate_suppliers" → Supplier + Supplier Discovery
  - "full_operations" → all engines
"""
from __future__ import annotations

from typing import Any


# Engine capabilities mapping
ENGINE_CAPABILITIES = {
    "inventory": {
        "provides": ["inventory_health", "reorder_plan", "stockout_risks"],
        "requires": ["products"],
        "optional": ["orders", "warehouse_data"],
    },
    "stock_prediction": {
        "provides": ["stock_forecast"],
        "requires": ["products", "orders"],
        "optional": ["seasonality", "trend_data"],
    },
    "supplier": {
        "provides": ["supplier_scores"],
        "requires": ["products"],
        "optional": ["supplier_data", "lead_times"],
    },
    "supplier_discovery": {
        "provides": ["new_suppliers"],
        "requires": ["category"],
        "optional": ["region", "min_rating"],
    },
    "shipping_optimization": {
        "provides": ["shipping_plan"],
        "requires": ["orders", "products"],
        "optional": ["carriers", "warehouse_locations"],
    },
    "returns_management": {
        "provides": ["return_analysis"],
        "requires": ["returns"],
        "optional": ["products", "policies"],
    },
}

# Goal → engine mapping
GOAL_ENGINE_MAP = {
    "manage_inventory": ["inventory", "stock_prediction"],
    "optimize_shipping": ["shipping_optimization", "inventory"],
    "evaluate_suppliers": ["supplier", "supplier_discovery"],
    "full_operations": ["inventory", "stock_prediction", "supplier", "shipping_optimization", "returns_management"],
    "handle_returns": ["returns_management"],
    "restock": ["inventory", "stock_prediction", "supplier"],
}


def create_plan(goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Create an execution plan for the Operations Agent.

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

    # Default: core operations
    return ["inventory", "stock_prediction", "supplier"]


def _build_engine_input(engine_name: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Build the input payload for a specific engine."""
    products = context.get("products", [])

    if engine_name == "inventory":
        return {
            "status": "success",
            "data": {
                "products": products,
                "orders": context.get("orders", []),
                "warehouse_data": context.get("warehouse_data", {}),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "stock_prediction":
        return {
            "status": "success",
            "data": {
                "products": products,
                "orders": context.get("orders", []),
                "seasonality": context.get("seasonality", {}),
                "trend_data": context.get("trend_data", {}),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "supplier":
        return {
            "status": "success",
            "data": {
                "products": products,
                "supplier_data": context.get("supplier_data", []),
                "lead_times": context.get("lead_times", {}),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "supplier_discovery":
        return {
            "status": "success",
            "data": {
                "category": context.get("category", ""),
                "region": context.get("region", ""),
                "min_rating": context.get("min_rating", 0),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "shipping_optimization":
        return {
            "status": "success",
            "data": {
                "orders": context.get("orders", []),
                "products": products,
                "carriers": context.get("carriers", []),
                "warehouse_locations": context.get("warehouse_locations", []),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "returns_management":
        return {
            "status": "success",
            "data": {
                "returns": context.get("returns", []),
                "products": products,
                "policies": context.get("policies", {}),
            },
            "meta": {},
            "error": None,
        }

    return {"status": "success", "data": context, "meta": {}, "error": None}


def _get_dependencies(engine_name: str, existing_steps: list[dict]) -> list[str]:
    """Determine which previous steps this engine depends on."""
    # Stock prediction can use inventory results
    if engine_name == "stock_prediction" and any(s["name"] == "inventory" for s in existing_steps):
        return ["inventory"]
    # Supplier discovery can use supplier scores
    if engine_name == "supplier_discovery" and any(s["name"] == "supplier" for s in existing_steps):
        return ["supplier"]
    # Shipping optimization can use inventory data
    if engine_name == "shipping_optimization" and any(s["name"] == "inventory" for s in existing_steps):
        return ["inventory"]
    return []


def _determine_strategy(goal: str, context: dict[str, Any]) -> str:
    """Determine operations strategy."""
    if "quick" in goal or "fast" in goal:
        return "quick_scan"
    if "full" in goal or "thorough" in goal:
        return "full_operations"
    if "restock" in goal or "reorder" in goal:
        return "restock_focused"
    if "ship" in goal or "fulfil" in goal:
        return "shipping_focused"
    if "supplier" in goal or "sourcing" in goal:
        return "supplier_focused"
    return "balanced"
