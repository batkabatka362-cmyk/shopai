"""Market Simulator Engine — scenario comparator.

Compares multiple scenarios and ranks them by expected outcome.
Produces risk analysis across all scenarios.
"""
from __future__ import annotations

import copy
from typing import Any


def compare_scenarios(
    price_impacts: list[dict[str, Any]],
    launch_simulations: list[dict[str, Any]],
    demand_model: dict[str, Any],
) -> dict[str, Any]:
    """Compare and rank scenarios, produce risk analysis."""
    try:
        price_impacts = copy.deepcopy(price_impacts)
        confidence = float(demand_model.get("confidence", 0.7))

        scored: list[dict[str, Any]] = []
        revenues: list[float] = []

        for impact in price_impacts:
            name = impact.get("scenario", "")
            revenue = float(impact.get("predicted_revenue", 0))
            units = float(impact.get("predicted_units", 0))
            margin = float(impact.get("margin_impact", 0))

            price_change = abs(float(impact.get("price_change_pct", 0)))
            risk_score = round(min(price_change / 30.0, 1.0), 2)
            if margin < 0:
                risk_score = min(risk_score + 0.3, 1.0)

            revenues.append(revenue)
            scored.append({
                "scenario": name,
                "predicted_revenue": revenue,
                "predicted_units": units,
                "confidence": round(confidence * (1 - risk_score * 0.2), 2),
                "risk_score": risk_score,
                "rank": 0,
            })

        scored.sort(key=lambda s: s["predicted_revenue"], reverse=True)
        for i, s in enumerate(scored):
            s["rank"] = i + 1

        risk_factors = []
        if any(s["risk_score"] > 0.7 for s in scored):
            risk_factors.append("High price volatility in some scenarios")
        if confidence < 0.6:
            risk_factors.append("Low model confidence due to limited data")

        best_scenario = scored[0]["scenario"] if scored else ""

        risk_analysis = {
            "worst_case_revenue": round(min(revenues), 2) if revenues else 0.0,
            "best_case_revenue": round(max(revenues), 2) if revenues else 0.0,
            "volatility_score": round(
                (max(revenues) - min(revenues)) / max(max(revenues), 1), 2
            ) if revenues else 0.0,
            "risk_factors": risk_factors,
        }

        return {
            "status": "success",
            "comparisons": scored,
            "best_scenario": best_scenario,
            "risk_analysis": risk_analysis,
        }
    except Exception as exc:
        return {
            "status": "error", "comparisons": [], "best_scenario": "",
            "risk_analysis": {}, "error": f"Scenario comparison failed: {exc}",
        }
