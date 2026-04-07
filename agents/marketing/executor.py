"""Marketing Agent executor — runs engines in sequence per plan.

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

    Example: Email marketing can use content generation results.
    """
    enriched = copy.deepcopy(engine_input)
    data = enriched.get("data", {})

    for dep_name in dependencies:
        dep_result = previous_results.get(dep_name, {})
        if dep_result.get("status") != "success":
            continue

        dep_data = dep_result.get("data", {})

        # Content generation → Email/Social/AB/Landing/Video enrichment
        if dep_name == "content_generation":
            if dep_data.get("marketing_copy"):
                data["_marketing_copy"] = dep_data["marketing_copy"]
            if dep_data.get("ad_copy"):
                data["_ad_copy"] = dep_data["ad_copy"]
            # Pass generated content as the content input
            data["content"] = dep_data

    enriched["data"] = data
    return enriched
