"""Product Agent executor — runs engines in sequence per plan.

Thin wrapper around ``agents.base.executor.execute_plan_base``.
The shared base owns the defensive step parsing, the retry
loop, and the registry lookup. This file only knows how to
wire Product-domain dependency results into downstream engine
inputs.
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

    Example: Product ranking can use scoring results.
    """
    enriched = copy.deepcopy(engine_input)
    data = enriched.get("data", {})

    for dep_name in dependencies:
        dep_result = previous_results.get(dep_name, {})
        if dep_result.get("status") != "success":
            continue

        dep_data = dep_result.get("data", {})

        # Product scoring → Product ranking enrichment
        if dep_name == "product_scoring":
            if dep_data.get("scored_products"):
                data["scored_products"] = dep_data["scored_products"]

        # Product filter → Pricing enrichment
        if dep_name == "product_filter":
            if dep_data.get("filtered_products"):
                data["products"] = dep_data["filtered_products"]

        # Pricing → Catalog / Profitability enrichment
        if dep_name == "pricing":
            if dep_data.get("price_recommendations"):
                data["_price_recommendations"] = dep_data["price_recommendations"]
                data["_pricing_data"] = dep_data["price_recommendations"]

    enriched["data"] = data
    return enriched
