"""
Main entry point for MOQ analysis.
Produces engine-contract output: {status, data, meta, error}.
"""

import time
from .data import TYPICAL_MOQS, STORAGE_COST_PER_CUFT, HOLDING_COST_PCTS
from .rules import (
    validate_moq_against_budget,
    validate_inventory_months,
    validate_sell_through,
    check_cash_reserve,
)
from .logic import decide_moq_strategy


SUPPLIER_TYPE_MOQ_FLOORS = {
    "alibaba": 500,
    "wholesale": 10,
    "pod": 1,
}


def _total_investment(unit_cost, moq, shipping_per_unit=0.0):
    """Capital required to place the minimum order."""
    return moq * (unit_cost + shipping_per_unit)


def _storage_cost_estimate(unit_volume_cuft, moq, months, region="us_west"):
    """Monthly warehousing cost for holding MOQ inventory."""
    rate = STORAGE_COST_PER_CUFT.get(region, STORAGE_COST_PER_CUFT["us_west"])
    total_cuft = unit_volume_cuft * moq
    return round(total_cuft * rate * months, 2)


def _cash_tied_up(investment, holding_months, annual_holding_pct=0.25):
    """Opportunity cost of capital locked in inventory."""
    monthly_rate = annual_holding_pct / 12.0
    return round(investment * monthly_rate * holding_months, 2)


def _break_even_units(total_cost, sell_price, variable_cost_per_sale=0.0):
    """Units that must sell to recover the full MOQ investment."""
    margin = sell_price - variable_cost_per_sale
    if margin <= 0:
        return float("inf")
    return int(-(-total_cost // margin))  # ceiling division


def _risk_assessment(investment, budget, sell_through_est, moq):
    """Quantify downside if the product under-performs."""
    unsold_units = int(moq * (1.0 - sell_through_est))
    capital_at_risk = round(investment * (1.0 - sell_through_est), 2)
    budget_exposure = round(capital_at_risk / budget * 100, 2) if budget > 0 else 100.0
    risk_level = "low" if budget_exposure < 5 else "medium" if budget_exposure < 15 else "high"
    return {
        "unsold_units": unsold_units,
        "capital_at_risk_usd": capital_at_risk,
        "budget_exposure_pct": budget_exposure,
        "risk_level": risk_level,
    }


def _compare_supplier_types(unit_cost, sell_price, unit_volume_cuft, region):
    """Side-by-side comparison across Alibaba, wholesale, and POD."""
    comparisons = {}
    pod_markup = 2.2  # POD typically costs ~2.2x the base manufacturing cost
    wholesale_markup = 1.35
    for stype, floor_moq in SUPPLIER_TYPE_MOQ_FLOORS.items():
        if stype == "pod":
            adj_cost = round(unit_cost * pod_markup, 2)
        elif stype == "wholesale":
            adj_cost = round(unit_cost * wholesale_markup, 2)
        else:
            adj_cost = unit_cost
        inv = _total_investment(adj_cost, floor_moq)
        storage = _storage_cost_estimate(unit_volume_cuft, floor_moq, months=3, region=region)
        margin_per_unit = round(sell_price - adj_cost, 2)
        comparisons[stype] = {
            "moq": floor_moq,
            "unit_cost_usd": adj_cost,
            "total_investment_usd": round(inv, 2),
            "storage_3mo_usd": storage,
            "margin_per_unit_usd": margin_per_unit,
        }
    return comparisons


def analyze_moq(input_payload):
    """
    Analyze MOQ requirements and financial impact.

    input_payload keys:
        unit_cost        (float) - manufacturer price per unit
        sell_price       (float) - intended retail price
        moq              (int)   - required minimum order quantity
        budget           (float) - total available budget
        unit_volume_cuft (float) - cubic feet per unit for storage
        monthly_demand   (int)   - estimated monthly unit sales
        region           (str)   - warehouse region key (default "us_west")
        shipping_per_unit(float) - inbound shipping cost per unit (default 0)
        sell_through_est (float) - expected sell-through rate 0-1 (default 0.7)
    """
    start = time.time()
    try:
        unit_cost = float(input_payload["unit_cost"])
        sell_price = float(input_payload["sell_price"])
        moq = int(input_payload["moq"])
        budget = float(input_payload["budget"])
        unit_vol = float(input_payload.get("unit_volume_cuft", 0.5))
        monthly_demand = int(input_payload.get("monthly_demand", 50))
        region = input_payload.get("region", "us_west")
        shipping = float(input_payload.get("shipping_per_unit", 0.0))
        sell_through = float(input_payload.get("sell_through_est", 0.70))

        investment = _total_investment(unit_cost, moq, shipping)
        months_of_stock = moq / monthly_demand if monthly_demand > 0 else float("inf")
        storage = _storage_cost_estimate(unit_vol, moq, months_of_stock, region)
        holding = _cash_tied_up(investment, months_of_stock)
        total_cost = round(investment + storage + holding, 2)
        be_units = _break_even_units(total_cost, sell_price)
        risk = _risk_assessment(investment, budget, sell_through, moq)
        comparisons = _compare_supplier_types(unit_cost, sell_price, unit_vol, region)

        budget_ok = validate_moq_against_budget(investment, budget)
        inv_months_ok = validate_inventory_months(months_of_stock)
        sell_ok = validate_sell_through(sell_through)
        cash_ok = check_cash_reserve(investment, budget)

        analysis = {
            "investment_usd": round(investment, 2),
            "months_of_stock": round(months_of_stock, 1),
            "storage_cost_usd": storage,
            "holding_cost_usd": holding,
            "total_landed_cost_usd": total_cost,
            "break_even_units": be_units,
            "risk": risk,
            "supplier_comparison": comparisons,
            "constraints": {
                "budget_ok": budget_ok,
                "inventory_months_ok": inv_months_ok,
                "sell_through_ok": sell_ok,
                "cash_reserve_ok": cash_ok,
            },
        }
        strategy = decide_moq_strategy(analysis, budget, sell_through)
        analysis["recommended_strategy"] = strategy

        return {
            "status": "success",
            "data": analysis,
            "meta": {
                "module": "moq_analyzer",
                "elapsed_ms": round((time.time() - start) * 1000, 1),
                "moq_input": moq,
                "budget_input": budget,
            },
            "error": None,
        }
    except (KeyError, ValueError, TypeError) as exc:
        return {
            "status": "error",
            "data": None,
            "meta": {"module": "moq_analyzer", "elapsed_ms": round((time.time() - start) * 1000, 1)},
            "error": str(exc),
        }
