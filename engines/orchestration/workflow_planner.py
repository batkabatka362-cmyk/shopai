"""Orchestration Engine — workflow planner.

Plan engine execution order from workflow definition.
"""
from __future__ import annotations

import copy
from typing import Any


def plan_workflow(
    **kwargs: Any,
) -> dict[str, Any]:
    """Plan workflow execution order.

    Args:
        **kwargs: Must include 'workflow' list with engine/dependency definitions.

    Returns:
        Structured dict with execution plan.
    """
    try:
        workflow = copy.deepcopy(kwargs.get("workflow", []))

        # Build adjacency and in-degree for topological sort
        nodes: dict[str, dict[str, Any]] = {}
        for step in workflow:
            engine = str(step.get("engine", ""))
            depends_on = step.get("depends_on", [])
            if isinstance(depends_on, str):
                depends_on = [depends_on] if depends_on else []
            nodes[engine] = {
                "engine": engine,
                "depends_on": depends_on,
                "config": step.get("config", {}),
            }

        # Topological sort
        in_degree: dict[str, int] = {n: 0 for n in nodes}
        for n, info in nodes.items():
            for dep in info["depends_on"]:
                if dep in in_degree:
                    in_degree[n] = in_degree.get(n, 0) + 1

        queue = [n for n, d in in_degree.items() if d == 0]
        execution_order: list[str] = []
        phases: list[list[str]] = []

        while queue:
            # All items in current queue can run in parallel
            phases.append(sorted(queue))
            execution_order.extend(sorted(queue))
            next_queue: list[str] = []
            for n in queue:
                for m, info in nodes.items():
                    if n in info["depends_on"]:
                        in_degree[m] -= 1
                        if in_degree[m] == 0:
                            next_queue.append(m)
            queue = next_queue

        # Check for cycles
        has_cycle = len(execution_order) < len(nodes)

        plan = [
            {"phase": i + 1, "engines": phase, "parallel": len(phase) > 1}
            for i, phase in enumerate(phases)
        ]

        return {
            "status": "success",
            "result": {
                "execution_plan": plan,
                "execution_order": execution_order,
                "total_phases": len(phases),
                "has_cycle": has_cycle,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Workflow planning failed: {exc}"}
