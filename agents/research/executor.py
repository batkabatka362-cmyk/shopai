"""Research Agent executor — runs engines in sequence per plan.

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

    Example: Trend Discovery can use Market Research's gap data.
    """
    enriched = copy.deepcopy(engine_input)
    data = enriched.get("data", {})

    for dep_name in dependencies:
        dep_result = previous_results.get(dep_name, {})
        if dep_result.get("status") != "success":
            continue

        dep_data = dep_result.get("data", {})

        # Market Research → Trend Discovery enrichment
        if dep_name == "market_research":
            # Pass gaps for trend context
            if dep_data.get("gaps"):
                data["_market_gaps"] = dep_data["gaps"]
            # Pass saturation for context
            if dep_data.get("saturation"):
                data["_market_saturation"] = dep_data["saturation"]
            # Pass market size for context
            if dep_data.get("market_size"):
                data["_market_size"] = dep_data["market_size"]

    enriched["data"] = data
    return enriched
