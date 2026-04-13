"""Simulation Lab — risk estimator.

Estimates risk for each scenario by examining variance, downside
exposure, loss probability, and individual risk factors.

Model note: Would use Mistral for validation of risk factor assessments.
"""
from __future__ import annotations

import copy
from typing import Any


def estimate_risks(
    simulation_results: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    environment_factors: dict[str, Any],
) -> dict[str, Any]:
    """Estimate risk for every simulated scenario.

    Args:
        simulation_results: List of SimulationResult dicts.
        predictions: List of OutcomePrediction dicts.
        environment_factors: EnvironmentFactors for context.

    Returns:
        Structured dict with a RiskAssessment per scenario.
    """
    try:
        sim_results = copy.deepcopy(simulation_results)
        pred_map = {p["scenario_id"]: p for p in copy.deepcopy(predictions)}
        env = copy.deepcopy(environment_factors)

        assessments: list[dict[str, Any]] = []
        for result in sim_results:
            sid = result.get("scenario_id", "unknown")
            pred = pred_map.get(sid, {})
            assessment = _assess_risk(result, pred, env)
            assessments.append(assessment)

        return {
            "status": "success",
            "assessments": assessments,
            "count": len(assessments),
        }
    except Exception as exc:
        return {
            "status": "error",
            "assessments": [],
            "count": 0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Single-scenario risk assessment
# ---------------------------------------------------------------------------

def _assess_risk(
    result: dict[str, Any],
    prediction: dict[str, Any],
    env: dict[str, Any],
) -> dict[str, Any]:
    """Assess risk for one scenario."""
    sid = result.get("scenario_id", "unknown")
    raw = result.get("raw_iterations", [])

    mean_profit = float(result.get("mean_profit", 0.0))
    std_profit = float(result.get("std_profit", 0.0))
    mean_revenue = float(result.get("mean_revenue", 0.0))
    std_revenue = float(result.get("std_revenue", 0.0))
    mean_margin = float(result.get("mean_margin", 0.0))
    p5_profit = float(result.get("profit_p5", 0.0))
    p5_revenue = float(result.get("revenue_p5", 0.0))

    volatility = float(env.get("volatility_factor", 0.15))
    competition = float(env.get("competition_pressure", 1.0))

    risk_factors: list[dict[str, Any]] = []

    # Factor 1: Variance risk
    cv_profit = (std_profit / abs(mean_profit)) if mean_profit != 0 else 1.0
    variance_severity = min(1.0, cv_profit)
    variance_likelihood = min(1.0, 0.3 + volatility)
    risk_factors.append({
        "name": "outcome_variance",
        "severity": round(variance_severity, 4),
        "likelihood": round(variance_likelihood, 4),
        "description": f"Profit coefficient of variation is {cv_profit:.2f}",
    })

    # Factor 2: Downside exposure
    loss_iterations = sum(1 for r in raw if r.get("profit", 0) < 0)
    total_iterations = max(len(raw), 1)
    prob_loss = loss_iterations / total_iterations
    max_loss = 0.0
    if raw:
        max_loss = abs(min(r.get("profit", 0) for r in raw))

    downside_severity = min(1.0, max_loss / max(abs(mean_profit), 1.0))
    risk_factors.append({
        "name": "downside_exposure",
        "severity": round(downside_severity, 4),
        "likelihood": round(prob_loss, 4),
        "description": f"Loss probability {prob_loss:.1%}, max loss {max_loss:.2f}",
    })

    # Factor 3: Margin risk
    margin_severity = max(0.0, min(1.0, 1.0 - mean_margin * 3.33))  # 30% margin = 0 risk
    margin_likelihood = 0.5 + volatility * 0.5
    risk_factors.append({
        "name": "margin_erosion",
        "severity": round(margin_severity, 4),
        "likelihood": round(min(1.0, margin_likelihood), 4),
        "description": f"Mean margin {mean_margin:.1%} — {'adequate' if mean_margin > 0.2 else 'thin'}",
    })

    # Factor 4: Competition risk
    comp_pressure = max(0.0, 1.0 - competition)  # competition < 1.0 means pressure
    risk_factors.append({
        "name": "competitive_pressure",
        "severity": round(comp_pressure, 4),
        "likelihood": round(min(1.0, 0.4 + comp_pressure * 0.6), 4),
        "description": f"Competition modifier at {competition:.2f}",
    })

    # Factor 5: Market volatility
    risk_factors.append({
        "name": "market_volatility",
        "severity": round(min(1.0, volatility * 2), 4),
        "likelihood": round(min(1.0, 0.3 + volatility), 4),
        "description": f"Market volatility factor {volatility:.2f}",
    })

    # Overall risk: weighted average of factor scores
    weighted_scores = []
    weights = [0.30, 0.30, 0.15, 0.15, 0.10]
    for factor, weight in zip(risk_factors, weights):
        score = factor["severity"] * factor["likelihood"]
        weighted_scores.append(score * weight)

    overall_risk = min(1.0, sum(weighted_scores) / max(sum(weights), 0.01))

    # Risk category
    if overall_risk < 0.15:
        category = "low"
    elif overall_risk < 0.35:
        category = "medium"
    elif overall_risk < 0.60:
        category = "high"
    else:
        category = "critical"

    return {
        "scenario_id": sid,
        "overall_risk": round(overall_risk, 4),
        "risk_category": category,
        "risk_factors": risk_factors,
        "max_loss_estimate": round(max_loss, 2),
        "probability_of_loss": round(prob_loss, 4),
    }
