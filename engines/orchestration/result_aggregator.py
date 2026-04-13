"""Orchestration Engine — result aggregator.

Aggregate results from multiple engine executions.
"""
from __future__ import annotations

import copy
from typing import Any


def aggregate_results(
    **kwargs: Any,
) -> dict[str, Any]:
    """Aggregate results from multiple engines.

    Args:
        **kwargs: Must include all prior stage data.

    Returns:
        Structured dict with aggregated results.
    """
    try:
        plan_data = kwargs.get("workflow_planner_data", {})
        dep_data = kwargs.get("dependency_resolver_data", {})
        sched_data = kwargs.get("parallel_scheduler_data", {})
        context = kwargs.get("context", {})

        execution_plan = plan_data.get("execution_plan", [])
        schedule = sched_data.get("schedule", [])
        total_time = sched_data.get("estimated_total_seconds", 0)
        total_engines = dep_data.get("total_engines", 0)

        # In production, this would collect actual engine results
        # Here we build the aggregation structure
        results: dict[str, Any] = {}
        for phase in execution_plan:
            for engine in phase.get("engines", []):
                results[engine] = {
                    "status": "pending",
                    "phase": phase.get("phase", 0),
                    "result": None,
                }

        timing = {
            "estimated_total_seconds": total_time,
            "phases": len(execution_plan),
            "schedule": schedule,
        }

        success_rate = 1.0  # All pending = assume success until executed

        return {
            "status": "success",
            "result": {
                "execution_plan": execution_plan,
                "results": results,
                "timing": timing,
                "success_rate": success_rate,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Result aggregation failed: {exc}"}
