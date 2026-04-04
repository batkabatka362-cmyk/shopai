"""Workflow Builder Engine — executor planner.

Plans execution with timing and parallelism information.
"""
from __future__ import annotations

from typing import Any


def plan_execution(
    designed_steps: list[dict[str, Any]],
    dependency_graph: dict[str, Any],
) -> dict[str, Any]:
    """Plan execution with timing and parallelism."""
    try:
        step_map = {s.get("step_id", ""): s for s in designed_steps}
        parallel_groups = dependency_graph.get("parallel_groups", [])
        ordered = dependency_graph.get("steps_ordered", [])

        # Calculate total estimated duration (parallel groups run concurrently)
        total_duration = 0.0
        for group in parallel_groups:
            group_max = 0.0
            for sid in group:
                step = step_map.get(sid, {})
                dur = float(step.get("estimated_duration_seconds", 2.0))
                group_max = max(group_max, dur)
            total_duration += group_max

        execution_plan = {
            "total_steps": len(designed_steps),
            "parallel_groups": parallel_groups,
            "estimated_duration_seconds": round(total_duration, 2),
            "execution_order": ordered,
        }

        return {"status": "success", "execution_plan": execution_plan}
    except Exception as exc:
        return {"status": "error", "execution_plan": {}, "error": f"Execution planning failed: {exc}"}
