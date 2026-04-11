"""Finance Agent executor — runs engines in sequence per plan.

Thin wrapper around ``agents.base.executor.execute_plan_base``.
"""
from __future__ import annotations

import copy
from typing import Any

from agents.base.executor import execute_plan_base


def execute_plan(plan: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Execute all engines in the plan sequentially."""
    return execute_plan_base(plan, context, _enrich_from_dependencies)


def _enrich_from_dependencies(
    engine_input: dict[str, Any],
    dependencies: list[str],
    previous_results: dict[str, Any],
) -> dict[str, Any]:
    """Enrich engine input with results from previous engine runs.

    Example: Forecasting can use financial analysis results.
    """
    enriched = copy.deepcopy(engine_input)
    data = enriched.get("data", {})

    for dep_name in dependencies:
        dep_result = previous_results.get(dep_name, {})
        if dep_result.get("status") != "success":
            continue

        dep_data = dep_result.get("data", {})

        # Financial → Forecasting/KPI enrichment
        if dep_name == "financial":
            if dep_data.get("pnl"):
                data["_pnl"] = dep_data["pnl"]
            if dep_data.get("margins"):
                data["_margins"] = dep_data["margins"]
            if dep_data.get("health_grade"):
                data["_health_grade"] = dep_data["health_grade"]

        # Profitability calculator → Pricing enrichment
        if dep_name == "profitability_calculator":
            if dep_data.get("true_costs"):
                data["_true_costs"] = dep_data["true_costs"]

        # Pricing → Profit optimization/Dynamic pricing enrichment
        if dep_name == "pricing":
            if dep_data.get("price_recommendations"):
                data["_price_recommendations"] = dep_data["price_recommendations"]

    enriched["data"] = data
    return enriched
