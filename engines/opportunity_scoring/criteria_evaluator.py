"""Opportunity Scoring Engine — criteria evaluator.

Evaluates each opportunity against scoring criteria:
market fit, strategic alignment, resource availability.
"""
from __future__ import annotations

import copy
from typing import Any


_DEFAULT_CRITERIA = {
    "market_fit": 0.3,
    "strategic_alignment": 0.25,
    "resource_availability": 0.2,
    "time_to_value": 0.25,
}


def evaluate_criteria(
    opportunities: list[dict[str, Any]],
    criteria: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate opportunities against criteria.

    Args:
        opportunities: List of opportunity dicts.
        criteria: Scoring criteria with weights.

    Returns:
        Structured dict with criteria evaluations.
    """
    try:
        opps = copy.deepcopy(opportunities)
        if not isinstance(criteria, dict):
            criteria = {}
        weights = criteria.get("weights", _DEFAULT_CRITERIA)

        evaluated: list[dict[str, Any]] = []

        for opp in opps:
            # Normalize: string opportunities → dict
            if isinstance(opp, str):
                opp = {"description": opp, "type": "detected"}
            scores: dict[str, float] = {}

            # Market fit: based on demand and market size
            demand = float(opp.get("demand", opp.get("demand_score", 0.5)))
            market_size = float(opp.get("market_size", opp.get("potential_revenue", 0)))
            scores["market_fit"] = round(min(1.0, demand * 0.6 + min(market_size / 500000, 0.4)), 3)

            # Strategic alignment: based on category match
            alignment = float(opp.get("strategic_alignment", 0.5))
            scores["strategic_alignment"] = round(alignment, 3)

            # Resource availability: inverse of effort
            effort_map = {"low": 0.9, "medium": 0.6, "high": 0.3}
            effort = str(opp.get("effort", "medium"))
            scores["resource_availability"] = effort_map.get(effort, 0.5)

            # Time to value: based on feasibility
            feasibility = float(opp.get("feasibility", 0.5))
            scores["time_to_value"] = round(feasibility, 3)

            # Weighted total
            total = 0.0
            for criterion, weight in weights.items():
                total += scores.get(criterion, 0.5) * float(weight)

            opp["criteria_scores"] = scores
            opp["criteria_total"] = round(total, 3)
            evaluated.append(opp)

        return {
            "status": "success",
            "evaluated": evaluated,
            "total_evaluated": len(evaluated),
        }
    except Exception as exc:
        return {
            "status": "error",
            "evaluated": [],
            "error": f"Criteria evaluation failed: {exc}",
        }
