"""Operations Agent planner — decides which engines to use and in what order.

Thin wrapper around ``agents.base.planner.create_plan_base``.
"""
from __future__ import annotations

from typing import Any

from agents.base.planner import create_plan_base, wrap_engine_input


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

GOAL_ENGINE_MAP = {
    "manage_inventory": ["inventory", "stock_prediction"],
    "optimize_shipping": ["shipping_optimization", "inventory"],
    "evaluate_suppliers": ["supplier", "supplier_discovery"],
    "full_operations": ["inventory", "stock_prediction", "supplier", "shipping_optimization", "returns_management"],
    "handle_returns": ["returns_management"],
    "restock": ["inventory", "stock_prediction", "supplier"],
}

DEFAULT_ENGINES = ["inventory", "stock_prediction", "supplier"]


def create_plan(goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Create an execution plan for the Operations Agent."""
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

    if engine_name == "inventory":
        return wrap_engine_input({
            "products": products,
            "orders": context.get("orders", []),
            "warehouse_data": context.get("warehouse_data", {}),
        })

    if engine_name == "stock_prediction":
        return wrap_engine_input({
            "products": products,
            "orders": context.get("orders", []),
            "seasonality": context.get("seasonality", {}),
            "trend_data": context.get("trend_data", {}),
        })

    if engine_name == "supplier":
        return wrap_engine_input({
            "products": products,
            "supplier_data": context.get("supplier_data", []),
            "lead_times": context.get("lead_times", {}),
        })

    if engine_name == "supplier_discovery":
        return wrap_engine_input({
            "category": context.get("category", ""),
            "region": context.get("region", ""),
            "min_rating": context.get("min_rating", 0),
        })

    if engine_name == "shipping_optimization":
        return wrap_engine_input({
            "orders": context.get("orders", []),
            "products": products,
            "carriers": context.get("carriers", []),
            "warehouse_locations": context.get("warehouse_locations", []),
        })

    if engine_name == "returns_management":
        return wrap_engine_input({
            "returns": context.get("returns", []),
            "products": products,
            "policies": context.get("policies", {}),
        })

    # Defensive fallback: never leak context. Pass 35.
    return wrap_engine_input({})


def _get_dependencies(engine_name: str, existing_steps: list[dict]) -> list[str]:
    """Determine which previous steps this engine depends on."""
    if engine_name == "stock_prediction" and any(s["name"] == "inventory" for s in existing_steps):
        return ["inventory"]
    if engine_name == "supplier_discovery" and any(s["name"] == "supplier" for s in existing_steps):
        return ["supplier"]
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
