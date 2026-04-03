"""Finance Agent planner — decides which engines to use and in what order.

Planning logic:
  1. Start with financial analysis (understand current state)
  2. Then forecasting (project future)
  3. Then pricing/profitability (optimize)
  4. Then discount/dynamic pricing (execute)

If goal is specific:
  - "optimize_profit" → financial, profitability, pricing, profit_optimization
  - "forecast_revenue" → financial, forecasting, kpi_tracking
  - "manage_pricing" → pricing, dynamic_pricing, price_elasticity
  - "reduce_costs" → financial, profitability, payment_optimization
  - "financial_health" → financial, kpi_tracking
"""
from __future__ import annotations

from typing import Any


# Engine capabilities mapping
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

# Goal → engine mapping
GOAL_ENGINE_MAP = {
    "optimize_profit": ["financial", "profitability_calculator", "pricing", "profit_optimization"],
    "forecast_revenue": ["financial", "forecasting", "kpi_tracking"],
    "manage_pricing": ["pricing", "dynamic_pricing", "price_elasticity"],
    "reduce_costs": ["financial", "profitability_calculator", "payment_optimization"],
    "financial_health": ["financial", "kpi_tracking"],
}


def create_plan(goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Create an execution plan for the Finance Agent.

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

    # Default: financial health check
    return ["financial", "kpi_tracking"]


def _build_engine_input(engine_name: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Build the input payload for a specific engine."""
    orders = context.get("orders", [])
    products = context.get("products", [])
    costs = context.get("costs", {})
    market_data = context.get("market_data", {})

    if engine_name == "financial":
        return {
            "status": "success",
            "data": {
                "orders": orders,
                "products": products,
                "date_range": context.get("date_range", {}),
                "currency": context.get("currency", "USD"),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "kpi_tracking":
        return {
            "status": "success",
            "data": {
                "orders": orders,
                "kpi_list": context.get("kpi_list", ["revenue", "aov", "conversion_rate", "cac"]),
                "period": context.get("period", "monthly"),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "forecasting":
        return {
            "status": "success",
            "data": {
                "orders": orders,
                "forecast_horizon": context.get("forecast_horizon", 90),
                "seasonality": context.get("seasonality", {}),
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

    if engine_name == "dynamic_pricing":
        return {
            "status": "success",
            "data": {
                "products": products,
                "demand_signals": context.get("demand_signals", {}),
                "rules": context.get("pricing_rules", {}),
                "bounds": context.get("price_bounds", {}),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "price_elasticity":
        return {
            "status": "success",
            "data": {
                "products": products,
                "price_history": context.get("price_history", []),
                "test_data": context.get("test_data", {}),
                "segments": context.get("segments", []),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "discount_strategy":
        return {
            "status": "success",
            "data": {
                "products": products,
                "margins": context.get("margins", {}),
                "current_discounts": context.get("current_discounts", []),
                "goals": context.get("discount_goals", {}),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "profit_optimization":
        return {
            "status": "success",
            "data": {
                "products": products,
                "costs": costs,
                "constraints": constraints,
                "targets": context.get("profit_targets", {}),
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

    # Fallback for engines like payment_optimization
    return {"status": "success", "data": context, "meta": {}, "error": None}


def _get_dependencies(engine_name: str, existing_steps: list[dict]) -> list[str]:
    """Determine which previous steps this engine depends on."""
    # Forecasting depends on financial analysis
    if engine_name == "forecasting" and any(s["name"] == "financial" for s in existing_steps):
        return ["financial"]
    # KPI tracking depends on financial analysis
    if engine_name == "kpi_tracking" and any(s["name"] == "financial" for s in existing_steps):
        return ["financial"]
    # Pricing depends on profitability calculator
    if engine_name == "pricing" and any(s["name"] == "profitability_calculator" for s in existing_steps):
        return ["profitability_calculator"]
    # Profit optimization depends on pricing
    if engine_name == "profit_optimization" and any(s["name"] == "pricing" for s in existing_steps):
        return ["pricing"]
    # Dynamic pricing depends on pricing
    if engine_name == "dynamic_pricing" and any(s["name"] == "pricing" for s in existing_steps):
        return ["pricing"]
    # Price elasticity depends on pricing
    if engine_name == "price_elasticity" and any(s["name"] == "pricing" for s in existing_steps):
        return ["pricing"]
    # Discount strategy depends on financial
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
