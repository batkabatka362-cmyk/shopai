"""
Scenario Modeler — Decision logic.

Comparison, risk adjustment, key driver identification, and
go/no-go recommendation functions that operate on scenario results.
"""

import math
from . import SCENARIO_WEIGHTS


def compare_scenarios(scenarios):
    """Rank scenarios by likelihood-weighted attractiveness. Returns ranked list."""
    if not scenarios:
        return {"ranked": [], "most_likely": None, "least_likely": None}

    scored = []
    for s in scenarios:
        weight = SCENARIO_WEIGHTS.get(s["label"], 0.10)
        attractiveness = s["profit"] * weight + s["margin"] * weight * 100
        scored.append({
            "label": s["label"],
            "profit": s["profit"],
            "margin": s["margin"],
            "weight": weight,
            "score": round(attractiveness, 2),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return {
        "ranked": scored,
        "most_likely": scored[0]["label"],
        "least_likely": scored[-1]["label"],
    }


def calculate_risk_adjusted_return(scenarios):
    """Compute risk-adjusted return using CV and Sharpe-like ratio."""
    if not scenarios:
        return {"expected_return": 0, "std_dev": 0, "cv": 0, "risk_adjusted_score": 0}

    profits, weights = [], []
    for s in scenarios:
        profits.append(s["profit"])
        weights.append(SCENARIO_WEIGHTS.get(s["label"], 0.10))

    total_weight = sum(weights) or 1
    expected_return = sum(p * w for p, w in zip(profits, weights)) / total_weight

    variance = sum(
        w * (p - expected_return) ** 2 for p, w in zip(profits, weights)
    ) / total_weight
    std_dev = math.sqrt(variance)
    cv = (std_dev / abs(expected_return)) if expected_return != 0 else float("inf")
    risk_adjusted_score = (expected_return / std_dev) if std_dev > 0 else 0

    max_loss = abs(min(profits)) if min(profits) < 0 else 0
    sortino_downside = math.sqrt(
        sum(w * min(0, p - expected_return) ** 2 for p, w in zip(profits, weights)) / total_weight
    )
    sortino = (expected_return / sortino_downside) if sortino_downside > 0 else None

    return {
        "expected_return": round(expected_return, 2),
        "std_dev": round(std_dev, 2),
        "coefficient_of_variation": round(cv, 4),
        "risk_adjusted_score": round(risk_adjusted_score, 4),
        "max_potential_loss": round(max_loss, 2),
        "sortino_ratio": round(sortino, 4) if sortino is not None else None,
    }


def identify_key_drivers(scenarios):
    """Sensitivity analysis: which variable swing causes the biggest profit change?"""
    if len(scenarios) < 2:
        return {"drivers": [], "top_driver": None}

    pessimistic = next((s for s in scenarios if s["label"] == "pessimistic"), None)
    optimistic = next((s for s in scenarios if s["label"] == "optimistic"), None)
    if not pessimistic or not optimistic:
        pessimistic = min(scenarios, key=lambda s: s["profit"])
        optimistic = max(scenarios, key=lambda s: s["profit"])

    variables = ["revenue", "total_costs", "volume", "price", "ad_spend"]
    drivers = []
    for var in variables:
        pess_val = pessimistic.get(var, 0)
        opt_val = optimistic.get(var, 0)
        delta = opt_val - pess_val
        pct_change = (delta / abs(pess_val) * 100) if pess_val != 0 else 0
        elasticity = (
            ((optimistic["profit"] - pessimistic["profit"]) / abs(pessimistic["profit"])) / (delta / abs(pess_val))
            if pess_val != 0 and pessimistic["profit"] != 0 else 0
        )
        drivers.append({
            "variable": var,
            "pessimistic_value": round(pess_val, 2),
            "optimistic_value": round(opt_val, 2),
            "absolute_delta": round(abs(delta), 2),
            "pct_change": round(pct_change, 2),
            "elasticity": round(elasticity, 4),
        })

    drivers.sort(key=lambda d: d["absolute_delta"], reverse=True)
    return {
        "drivers": drivers,
        "top_driver": drivers[0]["variable"] if drivers else None,
        "profit_swing": round(optimistic["profit"] - pessimistic["profit"], 2),
    }


def recommend_go_no_go(scenarios, budget=None, risk_tolerance=None):
    """
    Synthesize scenario analysis into GO / CONDITIONAL / NO_GO recommendation.
    GO: expected profitable AND pessimistic survivable.
    CONDITIONAL: expected profitable BUT pessimistic risky.
    NO_GO: expected unprofitable OR pessimistic catastrophic.
    """
    if not scenarios:
        return {"recommendation": "NO_GO", "reasons": ["No scenarios provided"]}

    expected = next((s for s in scenarios if s["label"] == "expected"), None)
    pessimistic = next((s for s in scenarios if s["label"] == "pessimistic"), None)
    risk_data = calculate_risk_adjusted_return(scenarios)

    reasons, score = [], 0

    if expected and expected["profit"] > 0:
        score += 2
        reasons.append(f"Expected scenario profitable: ${expected['profit']:,.2f}")
    else:
        score -= 2
        reasons.append("Expected scenario is not profitable")

    if pessimistic and pessimistic["profit"] > 0:
        score += 1
        reasons.append("Pessimistic scenario still profitable")
    elif pessimistic and budget and abs(pessimistic["profit"]) < budget * 0.5:
        reasons.append("Pessimistic loss within survivable range")
    elif pessimistic:
        score -= 2
        reasons.append(f"Pessimistic loss is severe: ${pessimistic['profit']:,.2f}")

    if risk_data["risk_adjusted_score"] > 1.0:
        score += 1
        reasons.append(f"Good risk/reward ratio: {risk_data['risk_adjusted_score']}")
    elif risk_data["risk_adjusted_score"] < 0:
        score -= 1
        reasons.append("Negative risk-adjusted return")

    if risk_tolerance and risk_data["max_potential_loss"] > risk_tolerance:
        score -= 2
        reasons.append(f"Max loss ${risk_data['max_potential_loss']:,.2f} exceeds tolerance")

    recommendation = "GO" if score >= 3 else ("CONDITIONAL" if score >= 0 else "NO_GO")
    return {
        "recommendation": recommendation,
        "score": score,
        "reasons": reasons,
        "risk_adjusted_score": risk_data["risk_adjusted_score"],
        "expected_return": risk_data["expected_return"],
    }
