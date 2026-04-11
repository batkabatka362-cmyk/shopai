"""Orchestration Engine — parallel scheduler.

Schedule parallel execution of engines within each phase.
"""
from __future__ import annotations

import copy
from typing import Any


def schedule_parallel(
    **kwargs: Any,
) -> dict[str, Any]:
    """Schedule parallel execution.

    Args:
        **kwargs: Must include plan and dependency data.

    Returns:
        Structured dict with parallel execution schedule.
    """
    try:
        plan_data = kwargs.get("workflow_planner_data", {})
        dep_data = kwargs.get("dependency_resolver_data", {})
        execution_plan = plan_data.get("execution_plan", [])
        context = kwargs.get("context", {})

        max_parallel = int(context.get("max_parallel", 4))

        schedule: list[dict[str, Any]] = []
        total_estimated_time = 0.0

        for phase in execution_plan:
            engines = phase.get("engines", [])
            phase_num = phase.get("phase", 0)

            # Split into batches if exceeding max_parallel
            batches: list[list[str]] = []
            for i in range(0, len(engines), max_parallel):
                batches.append(engines[i:i + max_parallel])

            phase_time = 0.0
            for batch in batches:
                # Estimate: each engine takes ~1s, parallel batch = max(individual times)
                batch_time = 1.0  # Simplified estimate
                phase_time += batch_time

            total_estimated_time += phase_time

            schedule.append({
                "phase": phase_num,
                "batches": batches,
                "num_batches": len(batches),
                "estimated_seconds": round(phase_time, 2),
            })

        return {
            "status": "success",
            "result": {
                "schedule": schedule,
                "total_phases": len(schedule),
                "estimated_total_seconds": round(total_estimated_time, 2),
                "max_parallel": max_parallel,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Parallel scheduling failed: {exc}"}
