"""Operations Agent executor — runs engines in sequence per plan.

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

    Example: Stock Prediction can use Inventory's stockout risk data.
    """
    enriched = copy.deepcopy(engine_input)
    data = enriched.get("data", {})

    for dep_name in dependencies:
        dep_result = previous_results.get(dep_name, {})
        if dep_result.get("status") != "success":
            continue

        dep_data = dep_result.get("data", {})

        # Inventory → Stock Prediction enrichment
        if dep_name == "inventory":
            if dep_data.get("stockout_risks"):
                data["_stockout_risks"] = dep_data["stockout_risks"]
            if dep_data.get("reorder_plan"):
                data["_reorder_plan"] = dep_data["reorder_plan"]
            if dep_data.get("inventory_health"):
                data["_inventory_health"] = dep_data["inventory_health"]

        # Supplier → Supplier Discovery enrichment
        if dep_name == "supplier":
            if dep_data.get("supplier_scores"):
                data["_supplier_scores"] = dep_data["supplier_scores"]

    enriched["data"] = data
    return enriched
