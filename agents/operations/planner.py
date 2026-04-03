"""Operations Agent planner — decides which engines to use and in what order.

Planning logic:
  1. Inventory engine first (understand current stock)
  2. Stock prediction for forecasting
  3. Supplier evaluation for sourcing
  4. Shipping optimization for fulfillment
  5. Returns management for reverse logistics

If goal is specific:
  - "manage inventory" → Inventory + Stock Prediction
  - "optimize shipping" → Shipping + Inventory
  - "evaluate suppliers" → Supplier + Supplier Discovery
  - "full operations" → all engines
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
        "optional": ["seasonality_data", "trend_data"],
    },
    "supplier": {
        "provides": ["supplier_scores"],
        "requires": ["products"],
        "optional": ["supplier_data", "order_history"],
    },
    "supplier_discovery": {
        "provides": ["new_suppliers"],
        "requires": ["category"],
        "optional": ["requirements", "region"],
    },
    "shipping_optimization": {
        "provides": ["shipping_plan"],
        "requires": ["orders", "products"],
        "optional": ["carriers", "destinations", "warehouse_locations"],
    },
    "returns_management": {
        "provides": ["return_analysis"],
        "requires": ["returns"],
        "optional": ["products", "orders"],
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

    # Default: inventory + stock prediction
    return ["inventory", "stock_prediction"]


def _build_engine_input(engine_name: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Build the input payload for a specific engine."""
    products = context.get("products", [])
    orders = context.get("orders", [])

    if engine_name == "inventory":
        return {
            "status": "success",
            "data": {
                "products": products,
                "orders": orders,
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
                "orders": orders,
                "seasonality_data": context.get("seasonality_data", {}),
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
                "order_history": context.get("order_history", []),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "supplier_discovery":
        return {
            "status": "success",
            "data": {
                "category": context.get("category", ""),
                "requirements": context.get("requirements", {}),
                "region": context.get("region", ""),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "shipping_optimization":
        return {
            "status": "success",
            "data": {
                "orders": orders,
                "products": products,
                "carriers": context.get("carriers", []),
                "destinations": context.get("destinations", []),
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
                "orders": orders,
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
    # Shipping can use inventory results
    if engine_name == "shipping_optimization" and any(s["name"] == "inventory" for s in existing_steps):
        return ["inventory"]
    # Supplier discovery can use supplier scores
    if engine_name == "supplier_discovery" and any(s["name"] == "supplier" for s in existing_steps):
        return ["supplier"]
    return []


def _determine_strategy(goal: str, context: dict[str, Any]) -> str:
    """Determine operations strategy."""
    if "urgent" in goal or "emergency" in goal:
        return "emergency_restock"
    if "optimize" in goal:
        return "optimization_focused"
    if "supplier" in goal:
        return "supplier_focused"
    if "ship" in goal:
        return "shipping_focused"
    if "return" in goal:
        return "returns_focused"
    return "balanced"
