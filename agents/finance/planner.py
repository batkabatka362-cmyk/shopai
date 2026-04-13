"""Finance Agent planner — decides which engines to use and in what order.

Thin wrapper around ``agents.base.planner.create_plan_base``.
"""
from __future__ import annotations

from typing import Any

from agents.base.planner import create_plan_base, wrap_engine_input


ENGINE_CAPABILITIES = {
    "financial": {
        "provides": ["pnl", "margins", "health_grade"],
        "requires": ["orders", "products"],
        "optional": ["date_range", "currency"],
    },
    "kpi_tracking": {
        "provides": ["kpi_trends"],
        "requires": ["orders"],
        "optional": ["kpi_list", "period"],
    },
    "forecasting": {
        "provides": ["revenue_forecast"],
        "requires": ["orders"],
        "optional": ["forecast_horizon", "seasonality"],
    },
    "pricing": {
        "provides": ["price_recommendations"],
        "requires": ["products", "market_data"],
        "optional": ["competitor_prices", "margins"],
    },
    "dynamic_pricing": {
        "provides": ["price_adjustments"],
        "requires": ["products", "demand_signals"],
        "optional": ["rules", "bounds"],
    },
    "price_elasticity": {
        "provides": ["elasticity_curves"],
        "requires": ["products", "price_history"],
        "optional": ["test_data", "segments"],
    },
    "discount_strategy": {
        "provides": ["discount_plan"],
        "requires": ["products", "margins"],
        "optional": ["current_discounts", "goals"],
    },
    "profit_optimization": {
        "provides": ["profit_plan"],
        "requires": ["products", "costs"],
        "optional": ["constraints", "targets"],
    },
    "profitability_calculator": {
        "provides": ["true_costs"],
        "requires": ["products", "costs"],
        "optional": ["shipping_costs", "tax_rates"],
    },
}

GOAL_ENGINE_MAP = {
    "optimize_profit": ["financial", "profitability_calculator", "pricing", "profit_optimization"],
    "forecast_revenue": ["financial", "forecasting", "kpi_tracking"],
    "manage_pricing": ["pricing", "dynamic_pricing", "price_elasticity"],
    "reduce_costs": ["financial", "profitability_calculator", "payment_optimization"],
    "financial_health": ["financial", "kpi_tracking"],
}

DEFAULT_ENGINES = ["financial", "kpi_tracking"]


def create_plan(goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Create an execution plan for the Finance Agent."""
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
    orders = context.get("orders", [])
    products = context.get("products", [])
    costs = context.get("costs", {})
    market_data = context.get("market_data", {})

    if engine_name == "financial":
        return wrap_engine_input({
            "orders": orders,
            "products": products,
            "date_range": context.get("date_range", {}),
            "currency": context.get("currency", "USD"),
        })

    if engine_name == "kpi_tracking":
        return wrap_engine_input({
            "orders": orders,
            "kpi_list": context.get("kpi_list", ["revenue", "aov", "conversion_rate", "cac"]),
            "period": context.get("period", "monthly"),
        })

    if engine_name == "forecasting":
        return wrap_engine_input({
            "orders": orders,
            "forecast_horizon": context.get("forecast_horizon", 90),
            "seasonality": context.get("seasonality", {}),
        })

    if engine_name == "pricing":
        return wrap_engine_input({
            "products": products,
            "market_data": market_data,
            "competitor_prices": context.get("competitor_prices", {}),
            "margins": context.get("margins", {}),
        })

    if engine_name == "dynamic_pricing":
        return wrap_engine_input({
            "products": products,
            "demand_signals": context.get("demand_signals", {}),
            "rules": context.get("pricing_rules", {}),
            "bounds": context.get("price_bounds", {}),
        })

    if engine_name == "price_elasticity":
        return wrap_engine_input({
            "products": products,
            "price_history": context.get("price_history", []),
            "test_data": context.get("test_data", {}),
            "segments": context.get("segments", []),
        })

    if engine_name == "discount_strategy":
        return wrap_engine_input({
            "products": products,
            "margins": context.get("margins", {}),
            "current_discounts": context.get("current_discounts", []),
            "goals": context.get("discount_goals", {}),
        })

    if engine_name == "profit_optimization":
        return wrap_engine_input({
            "products": products,
            "costs": costs,
            "constraints": constraints,
            "targets": context.get("profit_targets", {}),
        })

    if engine_name == "profitability_calculator":
        return wrap_engine_input({
            "products": products,
            "costs": costs,
            "shipping_costs": context.get("shipping_costs", {}),
            "tax_rates": context.get("tax_rates", {}),
        })

    # Defensive fallback: never leak context. Pass 35.
    return wrap_engine_input({})


def _get_dependencies(engine_name: str, existing_steps: list[dict]) -> list[str]:
    """Determine which previous steps this engine depends on."""
    if engine_name == "forecasting" and any(s["name"] == "financial" for s in existing_steps):
        return ["financial"]
    if engine_name == "kpi_tracking" and any(s["name"] == "financial" for s in existing_steps):
        return ["financial"]
    if engine_name == "pricing" and any(s["name"] == "profitability_calculator" for s in existing_steps):
        return ["profitability_calculator"]
    if engine_name == "profit_optimization" and any(s["name"] == "pricing" for s in existing_steps):
        return ["pricing"]
    if engine_name == "dynamic_pricing" and any(s["name"] == "pricing" for s in existing_steps):
        return ["pricing"]
    if engine_name == "price_elasticity" and any(s["name"] == "pricing" for s in existing_steps):
        return ["pricing"]
    if engine_name == "discount_strategy" and any(s["name"] == "financial" for s in existing_steps):
        return ["financial"]
    return []


def _determine_strategy(goal: str, context: dict[str, Any]) -> str:
    """Determine financial strategy."""
    if "quick" in goal or "fast" in goal:
        return "quick_review"
    if "optimize" in goal or "profit" in goal:
        return "profit_optimization"
    if "forecast" in goal:
        return "forecasting_focused"
    if "pricing" in goal or "price" in goal:
        return "pricing_focused"
    if "cost" in goal or "reduce" in goal:
        return "cost_reduction"
    if "health" in goal:
        return "health_check"
    return "balanced"
