"""Content Agent executor — runs engines in sequence per plan.

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

    Example: Search Optimization can use Product Description's generated copy.
    """
    enriched = copy.deepcopy(engine_input)
    data = enriched.get("data", {})

    for dep_name in dependencies:
        dep_result = previous_results.get(dep_name, {})
        if dep_result.get("status") != "success":
            continue

        dep_data = dep_result.get("data", {})

        # Product Description → Search Optimization / Video Marketing enrichment
        if dep_name == "product_description":
            if dep_data.get("descriptions"):
                data["_descriptions"] = dep_data["descriptions"]
            if dep_data.get("bullet_points"):
                data["_bullet_points"] = dep_data["bullet_points"]

        # Content Generation → Search Optimization enrichment
        if dep_name == "content_generation":
            if dep_data.get("blog_posts"):
                data["_blog_posts"] = dep_data["blog_posts"]
            if dep_data.get("ad_copy"):
                data["_ad_copy"] = dep_data["ad_copy"]

    enriched["data"] = data
    return enriched
