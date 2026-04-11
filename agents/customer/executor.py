"""Customer Agent executor — runs engines in sequence per plan.

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

    Example: Churn Prediction can use Segmentation's RFM data.
    """
    enriched = copy.deepcopy(engine_input)
    data = enriched.get("data", {})

    for dep_name in dependencies:
        dep_result = previous_results.get(dep_name, {})
        if dep_result.get("status") != "success":
            continue

        dep_data = dep_result.get("data", {})

        # Customer Segmentation → Churn Prediction / Audience Targeting enrichment
        if dep_name == "customer_segmentation":
            if dep_data.get("segments"):
                data["_segments"] = dep_data["segments"]
            if dep_data.get("rfm_analysis"):
                data["_rfm_analysis"] = dep_data["rfm_analysis"]

        # Sentiment Analysis → Review Management enrichment
        if dep_name == "sentiment_analysis":
            if dep_data.get("sentiment_scores"):
                data["_sentiment_scores"] = dep_data["sentiment_scores"]

    enriched["data"] = data
    return enriched
