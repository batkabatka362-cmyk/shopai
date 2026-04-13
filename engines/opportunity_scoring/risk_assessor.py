"""Opportunity Scoring Engine — risk assessor.

Assesses risk per opportunity: market risk, execution risk,
financial risk, and competitive risk.
"""
from __future__ import annotations

import copy
from typing import Any


def assess_risk(
    evaluated: list[dict[str, Any]],
    risk_tolerance: str = "moderate",
) -> dict[str, Any]:
    """Assess risk for each evaluated opportunity.

    Args:
        evaluated: Criteria-evaluated opportunities.
        risk_tolerance: Risk tolerance level (conservative, moderate, aggressive).

    Returns:
        Structured dict with risk assessments.
    """
    try:
        opps = copy.deepcopy(evaluated)

        tolerance_multiplier = {
            "conservative": 1.3,
            "moderate": 1.0,
            "aggressive": 0.7,
        }
        multiplier = tolerance_multiplier.get(risk_tolerance, 1.0)

        assessed: list[dict[str, Any]] = []

        for opp in opps:
            feasibility = float(opp.get("feasibility", 0.5))
            demand = float(opp.get("demand", opp.get("demand_score", 0.5)))
            effort = str(opp.get("effort", "medium"))

            # Market risk: low demand = high risk
            market_risk = round((1.0 - demand) * multiplier, 3)

            # Execution risk: low feasibility or high effort = high risk
            effort_risk = {"low": 0.2, "medium": 0.5, "high": 0.8}
            exec_risk = round(
                ((1.0 - feasibility) * 0.5 + effort_risk.get(effort, 0.5) * 0.5) * multiplier,
                3,
            )

            # Financial risk: based on investment needed vs return
            potential = float(opp.get("potential_revenue", opp.get("market_size", 0)))
            fin_risk = round(
                max(0, min(1.0, 0.5 - min(potential / 1000000, 0.3))) * multiplier,
                3,
            )

            overall_risk = round(
                market_risk * 0.4 + exec_risk * 0.35 + fin_risk * 0.25,
                3,
            )

            if overall_risk >= 0.7:
                risk_level = "high"
            elif overall_risk >= 0.4:
                risk_level = "medium"
            else:
                risk_level = "low"

            opp["risk"] = risk_level
            opp["risk_score"] = overall_risk
            opp["risk_factors"] = {
                "market_risk": min(1.0, market_risk),
                "execution_risk": min(1.0, exec_risk),
                "financial_risk": min(1.0, fin_risk),
            }
            assessed.append(opp)

        return {
            "status": "success",
            "assessed": assessed,
            "total_assessed": len(assessed),
        }
    except Exception as exc:
        return {
            "status": "error",
            "assessed": [],
            "error": f"Risk assessment failed: {exc}",
        }
