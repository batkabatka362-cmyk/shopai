"""Simulation Lab — result analyzer.

Analyzes simulation results to find patterns, strengths, weaknesses,
stability scores, and upside/downside characteristics.

Model note: Would use Mistral for deeper analytical pattern recognition.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_results(
    simulation_results: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    scenarios: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze simulation results and identify patterns.

    Args:
        simulation_results: List of SimulationResult dicts.
        predictions: List of OutcomePrediction dicts.
        scenarios: Original scenario dicts for context.

    Returns:
        Structured dict with an AnalysisResult per scenario.
    """
    try:
        sim_results = copy.deepcopy(simulation_results)
        preds = {p["scenario_id"]: p for p in copy.deepcopy(predictions)}
        scen_map = {s["scenario_id"]: s for s in copy.deepcopy(scenarios)}

        analyses: list[dict[str, Any]] = []
        for result in sim_results:
            sid = result.get("scenario_id", "unknown")
            pred = preds.get(sid, {})
            scenario = scen_map.get(sid, {})
            analysis = _analyze_single(result, pred, scenario)
            analyses.append(analysis)

        return {
            "status": "success",
            "analyses": analyses,
            "count": len(analyses),
        }
    except Exception as exc:
        return {
            "status": "error",
            "analyses": [],
            "count": 0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Single-scenario analysis
# ---------------------------------------------------------------------------

def _analyze_single(
    result: dict[str, Any],
    prediction: dict[str, Any],
    scenario: dict[str, Any],
) -> dict[str, Any]:
    """Analyze one scenario's simulation results."""
    sid = result.get("scenario_id", "unknown")
    label = scenario.get("label", sid)

    mean_rev = float(result.get("mean_revenue", 0.0))
    mean_profit = float(result.get("mean_profit", 0.0))
    mean_margin = float(result.get("mean_margin", 0.0))
    std_rev = float(result.get("std_revenue", 0.0))
    std_profit = float(result.get("std_profit", 0.0))
    p5_profit = float(result.get("profit_p5", 0.0))
    p95_profit = float(result.get("profit_p95", 0.0))
    p5_rev = float(result.get("revenue_p5", 0.0))
    p95_rev = float(result.get("revenue_p95", 0.0))

    predicted_risk = float(prediction.get("predicted_risk", 0.5))
    predicted_roi = float(prediction.get("predicted_roi", 0.0))

    strengths: list[str] = []
    weaknesses: list[str] = []
    patterns: list[str] = []

    # --- Strengths ---
    if mean_margin > 0.30:
        strengths.append(f"Strong margin ({mean_margin:.0%}) provides cost buffer")
    if mean_profit > 0 and p5_profit > 0:
        strengths.append("Profitable even in worst-case (p5) scenarios")
    if predicted_roi > 0.5:
        strengths.append(f"High ROI ({predicted_roi:.1%}) indicates efficient capital use")
    if std_rev > 0 and (std_rev / mean_rev) < 0.15 and mean_rev > 0:
        strengths.append("Low revenue variance — predictable outcomes")
    if predicted_risk < 0.25:
        strengths.append("Low overall risk profile")

    # --- Weaknesses ---
    if mean_margin < 0.10:
        weaknesses.append(f"Thin margin ({mean_margin:.0%}) leaves little room for error")
    if p5_profit < 0:
        weaknesses.append(f"Downside risk: worst-case shows loss of {abs(p5_profit):.2f}")
    if predicted_risk > 0.6:
        weaknesses.append("High risk profile — significant outcome uncertainty")
    if predicted_roi < 0.1 and mean_profit > 0:
        weaknesses.append(f"Low ROI ({predicted_roi:.1%}) — capital may be better deployed elsewhere")
    if mean_rev > 0 and (std_rev / mean_rev) > 0.35:
        weaknesses.append("High revenue variance — outcomes are unpredictable")

    # --- Patterns ---
    rev_spread = p95_rev - p5_rev
    profit_spread = p95_profit - p5_profit
    if mean_rev > 0 and rev_spread / mean_rev > 0.5:
        patterns.append("Wide revenue spread suggests high sensitivity to market conditions")
    if profit_spread > 0 and p95_profit > abs(p5_profit) * 2:
        patterns.append("Upside potential significantly exceeds downside risk (positive skew)")
    elif p5_profit < 0 and abs(p5_profit) > p95_profit * 0.5:
        patterns.append("Downside risk is proportionally large relative to upside (negative skew)")

    variation_type = scenario.get("variation_type", "")
    if variation_type == "aggressive" and mean_profit > 0:
        patterns.append("Aggressive parameters still yield positive expected profit")
    if variation_type == "conservative" and predicted_risk < 0.2:
        patterns.append("Conservative approach confirms low-risk profile")
    if variation_type == "edge_case":
        if mean_profit > 0:
            patterns.append("Strategy remains profitable even at constraint boundaries")
        else:
            patterns.append("Strategy breaks down at constraint boundaries — guard rails needed")

    # --- Stability score ---
    cv_rev = (std_rev / mean_rev) if mean_rev > 0 else 1.0
    cv_profit = (std_profit / abs(mean_profit)) if mean_profit != 0 else 1.0
    stability = max(0.0, min(1.0, 1.0 - (cv_rev * 0.5 + cv_profit * 0.5)))

    # --- Upside / downside ---
    upside = max(0.0, p95_profit - mean_profit)
    downside = max(0.0, mean_profit - p5_profit)

    if not strengths:
        strengths.append("No notable strengths identified")
    if not weaknesses:
        weaknesses.append("No notable weaknesses identified")
    if not patterns:
        patterns.append("Standard distribution — no unusual patterns detected")

    return {
        "scenario_id": sid,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "patterns": patterns,
        "stability_score": round(stability, 4),
        "upside_potential": round(upside, 2),
        "downside_risk": round(downside, 2),
    }
