"""Orchestration Engine — dependency resolver.

Resolve engine dependencies and validate the dependency graph.
"""
from __future__ import annotations

import copy
from typing import Any


def resolve_dependencies(
    **kwargs: Any,
) -> dict[str, Any]:
    """Resolve engine dependencies.

    Args:
        **kwargs: Must include workflow and plan data.

    Returns:
        Structured dict with resolved dependency graph.
    """
    try:
        workflow = copy.deepcopy(kwargs.get("workflow", []))
        plan_data = kwargs.get("workflow_planner_data", {})
        execution_order = plan_data.get("execution_order", [])
        has_cycle = plan_data.get("has_cycle", False)

        if has_cycle:
            return {
                "status": "success",
                "result": {
                    "resolved": False,
                    "error": "Circular dependency detected in workflow",
                    "graph": {},
                },
            }

        # Build resolved dependency graph
        graph: dict[str, dict[str, Any]] = {}
        all_engines = {str(s.get("engine", "")) for s in workflow}

        for step in workflow:
            engine = str(step.get("engine", ""))
            depends_on = step.get("depends_on", [])
            if isinstance(depends_on, str):
                depends_on = [depends_on] if depends_on else []

            # Validate dependencies exist
            missing = [d for d in depends_on if d not in all_engines]

            graph[engine] = {
                "depends_on": depends_on,
                "missing_deps": missing,
                "order": execution_order.index(engine) if engine in execution_order else -1,
                "valid": len(missing) == 0,
            }

        all_valid = all(g["valid"] for g in graph.values())

        return {
            "status": "success",
            "result": {
                "resolved": all_valid,
                "graph": graph,
                "total_engines": len(graph),
                "valid_count": sum(1 for g in graph.values() if g["valid"]),
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Dependency resolution failed: {exc}"}
