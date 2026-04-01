"""
Scenario Modeler — Main entry point.

Generates pessimistic, expected, and optimistic scenarios with full
financial projections. Supports custom "what if" overrides for price,
volume, and ad spend. Returns engine-contract response.
"""

import time
from . import SCENARIO_WEIGHTS, SCENARIO_MULTIPLIERS


def _calculate_scenario(base, multiplier, label, overrides=None):
    """Build a single scenario projection from base inputs and a multiplier."""
    price = base.get("price", 0)
    volume = base.get("volume", 0)
    fixed_costs = base.get("fixed_costs", 0)
    variable_cost_per_unit = base.get("variable_cost_per_unit", 0)
    ad_spend = base.get("ad_spend", 0)
    monthly_overhead = base.get("monthly_overhead", 0)

    if overrides:
        price = overrides.get("price", price)
        volume = overrides.get("volume", volume)
        ad_spend = overrides.get("ad_spend", ad_spend)

    adjusted_volume = volume * multiplier
    revenue = price * adjusted_volume
    variable_costs = variable_cost_per_unit * adjusted_volume
    total_costs = fixed_costs + variable_costs + ad_spend + monthly_overhead
    profit = revenue - total_costs
    margin = (profit / revenue * 100) if revenue > 0 else 0
    cash_flow = profit - base.get("debt_service", 0)

    monthly_profit = profit / 12 if profit != 0 else 0
    if monthly_profit > 0:
        break_even_months = total_costs / monthly_profit
    elif monthly_profit == 0:
        break_even_months = float("inf")
    else:
        break_even_months = -1  # never breaks even

    return {
        "label": label,
        "multiplier": multiplier,
        "revenue": round(revenue, 2),
        "volume": round(adjusted_volume, 2),
        "price": round(price, 2),
        "total_costs": round(total_costs, 2),
        "profit": round(profit, 2),
        "margin": round(margin, 2),
        "cash_flow": round(cash_flow, 2),
        "break_even_months": round(break_even_months, 1) if break_even_months != float("inf") else None,
        "ad_spend": round(ad_spend, 2),
    }


def _risk_weighted_value(scenarios):
    """Compute risk-weighted expected value across scenarios."""
    weighted_profit = 0
    weighted_revenue = 0
    weighted_cash_flow = 0
    for s in scenarios:
        weight = SCENARIO_WEIGHTS.get(s["label"], 0)
        weighted_profit += s["profit"] * weight
        weighted_revenue += s["revenue"] * weight
        weighted_cash_flow += s["cash_flow"] * weight
    return {
        "weighted_profit": round(weighted_profit, 2),
        "weighted_revenue": round(weighted_revenue, 2),
        "weighted_cash_flow": round(weighted_cash_flow, 2),
    }


def _downside_protection(scenarios):
    """Identify worst-case financial impact across all scenarios."""
    worst = min(scenarios, key=lambda s: s["profit"])
    return {
        "worst_scenario": worst["label"],
        "worst_profit": worst["profit"],
        "worst_margin": worst["margin"],
        "worst_cash_flow": worst["cash_flow"],
        "max_loss": abs(worst["profit"]) if worst["profit"] < 0 else 0,
    }


def _build_custom_scenarios(base, custom_params):
    """Generate custom what-if scenarios from user-supplied parameter lists."""
    results = []
    for idx, params in enumerate(custom_params):
        label = params.get("name", f"custom_{idx + 1}")
        overrides = {k: v for k, v in params.items() if k != "name"}
        scenario = _calculate_scenario(base, 1.0, label, overrides=overrides)
        results.append(scenario)
    return results


def model_scenarios(input_payload):
    """
    Main engine function. Accepts input_payload dict and returns
    engine contract: {status, data, meta, error}.

    input_payload keys:
        price, volume, fixed_costs, variable_cost_per_unit,
        ad_spend, monthly_overhead, debt_service (all numeric)
        budget (total risk budget)
        custom_scenarios (optional list of dicts with overrides)
    """
    start_time = time.time()
    try:
        base = input_payload or {}
        required = ["price", "volume", "fixed_costs", "variable_cost_per_unit"]
        missing = [k for k in required if k not in base]
        if missing:
            return {
                "status": "error",
                "data": None,
                "meta": {"module": "scenario_modeler"},
                "error": f"Missing required fields: {', '.join(missing)}",
            }

        default_scenarios = []
        for label, mult in SCENARIO_MULTIPLIERS.items():
            scenario = _calculate_scenario(base, mult, label)
            default_scenarios.append(scenario)

        custom_scenarios = []
        if "custom_scenarios" in base and isinstance(base["custom_scenarios"], list):
            custom_scenarios = _build_custom_scenarios(base, base["custom_scenarios"])

        all_scenarios = default_scenarios + custom_scenarios
        risk_weighted = _risk_weighted_value(default_scenarios)
        downside = _downside_protection(all_scenarios)

        elapsed = round(time.time() - start_time, 4)
        return {
            "status": "success",
            "data": {
                "scenarios": all_scenarios,
                "risk_weighted_expected_value": risk_weighted,
                "downside_protection": downside,
            },
            "meta": {
                "module": "scenario_modeler",
                "scenario_count": len(all_scenarios),
                "default_count": len(default_scenarios),
                "custom_count": len(custom_scenarios),
                "elapsed_seconds": elapsed,
            },
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "error",
            "data": None,
            "meta": {"module": "scenario_modeler"},
            "error": str(exc),
        }
