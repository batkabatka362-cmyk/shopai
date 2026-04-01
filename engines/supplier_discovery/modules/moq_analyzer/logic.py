"""
Decision functions for MOQ strategy, optimal ordering, and negotiation planning.
"""

import math
from .rules import (
    MAX_INVENTORY_INVESTMENT_PCT,
    MAX_MONTHS_INVENTORY,
    MIN_SELL_THROUGH_RATE,
)
from .knowledge import calculate_eoq, get_moq_reduction_strategies


def decide_moq_strategy(analysis, budget, sell_through_est):
    """
    Decide whether to accept MOQ, negotiate, or find an alternative supplier.

    Returns a dict with decision, reasoning list, and confidence score.
    """
    constraints = analysis.get("constraints", {})
    risk = analysis.get("risk", {})
    investment = analysis.get("investment_usd", 0)

    passing = sum(1 for v in constraints.values() if v)
    total = len(constraints)

    # All constraints pass and low risk -> accept
    if passing == total and risk.get("risk_level") == "low":
        return {
            "decision": "accept",
            "confidence": 0.90,
            "reasons": ["All budget and inventory constraints satisfied.", "Risk level is low."],
        }

    # High risk or budget blown -> find alternative (POD / wholesale)
    if risk.get("risk_level") == "high" or not constraints.get("budget_ok"):
        reasons = []
        if not constraints.get("budget_ok"):
            reasons.append(
                f"Investment ${investment:,.0f} exceeds "
                f"{MAX_INVENTORY_INVESTMENT_PCT * 100:.0f}% of budget."
            )
        if risk.get("risk_level") == "high":
            reasons.append(
                f"Budget exposure is {risk.get('budget_exposure_pct', 0):.1f}% — too risky."
            )
        return {
            "decision": "find_alternative",
            "confidence": 0.85,
            "reasons": reasons,
            "suggested_types": ["pod", "wholesale"],
        }

    # Medium risk or partial constraint failure -> negotiate
    reasons = []
    if not constraints.get("inventory_months_ok"):
        reasons.append(
            f"Inventory covers > {MAX_MONTHS_INVENTORY} months — negotiate lower MOQ."
        )
    if not constraints.get("sell_through_ok"):
        reasons.append(
            f"Estimated sell-through {sell_through_est:.0%} is below "
            f"minimum {MIN_SELL_THROUGH_RATE:.0%}."
        )
    if not constraints.get("cash_reserve_ok"):
        reasons.append("Insufficient cash reserve after purchase — request smaller first order.")
    if not reasons:
        reasons.append("Moderate risk; negotiating a reduced MOQ is prudent.")

    return {
        "decision": "negotiate",
        "confidence": 0.75,
        "reasons": reasons,
    }


def calculate_optimal_order(demand_estimate, moq, storage_cost_per_unit_month,
                            unit_cost=0.0, ordering_cost=50.0):
    """
    Find the order quantity that minimizes total cost while respecting MOQ.

    Uses Economic Order Quantity as a starting point, then clamps to MOQ floor.
    Returns dict with optimal_qty, total_annual_cost breakdown, and comparison
    versus ordering exactly at MOQ.
    """
    annual_demand = demand_estimate * 12
    if annual_demand <= 0 or storage_cost_per_unit_month <= 0:
        return {"optimal_qty": moq, "note": "Insufficient data for optimization."}

    annual_holding = storage_cost_per_unit_month * 12
    eoq = calculate_eoq(annual_demand, ordering_cost, annual_holding)
    optimal_qty = max(eoq, moq)

    # Cost at optimal qty
    orders_per_year_opt = annual_demand / optimal_qty
    ordering_total_opt = orders_per_year_opt * ordering_cost
    holding_total_opt = (optimal_qty / 2.0) * annual_holding
    purchase_total_opt = annual_demand * unit_cost
    total_opt = round(ordering_total_opt + holding_total_opt + purchase_total_opt, 2)

    # Cost at exactly MOQ for comparison
    orders_per_year_moq = annual_demand / moq if moq > 0 else 0
    ordering_total_moq = orders_per_year_moq * ordering_cost
    holding_total_moq = (moq / 2.0) * annual_holding
    total_moq = round(ordering_total_moq + holding_total_moq + purchase_total_opt, 2)

    savings = round(total_moq - total_opt, 2)

    return {
        "eoq_raw": eoq,
        "optimal_qty": optimal_qty,
        "orders_per_year": round(orders_per_year_opt, 1),
        "annual_ordering_cost": round(ordering_total_opt, 2),
        "annual_holding_cost": round(holding_total_opt, 2),
        "annual_purchase_cost": round(purchase_total_opt, 2),
        "total_annual_cost": total_opt,
        "moq_total_annual_cost": total_moq,
        "savings_vs_moq": savings,
    }


def negotiate_moq_plan(current_moq, target_moq, unit_cost=None, budget=None):
    """
    Build a negotiation strategy to reduce MOQ from current to target.

    Returns a phased plan with tactics ranked by likelihood of success.
    """
    if target_moq >= current_moq:
        return {"plan": "No negotiation needed; target MOQ >= current MOQ."}

    reduction_pct = round((1 - target_moq / current_moq) * 100, 1)
    strategies = get_moq_reduction_strategies(reduction_pct)

    phases = []

    # Phase 1: offer higher unit price for lower MOQ
    if unit_cost is not None:
        premium_pct = min(reduction_pct * 0.3, 20.0)  # up to 20% premium
        offer_price = round(unit_cost * (1 + premium_pct / 100), 2)
        phases.append({
            "phase": 1,
            "tactic": "price_premium",
            "description": f"Offer ${offer_price:.2f}/unit (+{premium_pct:.1f}%) for MOQ of {target_moq}.",
            "success_likelihood": 0.55 if reduction_pct <= 50 else 0.25,
        })

    # Phase 2: tiered commitment
    mid_moq = int((current_moq + target_moq) / 2)
    phases.append({
        "phase": 2 if phases else 1,
        "tactic": "tiered_commitment",
        "description": (
            f"Propose trial order of {target_moq} units, scaling to "
            f"{mid_moq} then {current_moq} over 3 orders."
        ),
        "success_likelihood": 0.60,
    })

    # Phase 3: combine products or buyers
    phases.append({
        "phase": len(phases) + 1,
        "tactic": "order_consolidation",
        "description": "Combine with other product lines or co-buy with another seller to meet MOQ.",
        "success_likelihood": 0.45,
    })

    # Phase 4: seasonal / trade-show timing
    phases.append({
        "phase": len(phases) + 1,
        "tactic": "seasonal_timing",
        "description": "Approach supplier during low season or at trade shows for flexibility.",
        "success_likelihood": 0.40,
    })

    return {
        "current_moq": current_moq,
        "target_moq": target_moq,
        "reduction_pct": reduction_pct,
        "applicable_strategies": strategies,
        "negotiation_phases": phases,
    }
