"""Workflow Builder Engine — dependency resolver.

Resolves step dependencies and determines execution order using topological sort.
"""
from __future__ import annotations

from typing import Any


def resolve_dependencies(
    designed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Resolve dependencies and produce execution order."""
    try:
        step_ids = [s.get("step_id", "") for s in designed_steps]
        step_map = {s.get("step_id", ""): s for s in designed_steps}

        # Build adjacency and in-degree
        in_degree: dict[str, int] = {sid: 0 for sid in step_ids}
        dependents: dict[str, list[str]] = {sid: [] for sid in step_ids}
        dependencies: dict[str, list[str]] = {}

        for step in designed_steps:
            sid = step.get("step_id", "")
            deps = step.get("depends_on", [])
            # Map depends_on engine names to step_ids
            resolved_deps = []
            for dep in deps:
                for other in designed_steps:
                    if other.get("engine") == dep or other.get("step_id") == dep:
                        resolved_deps.append(other.get("step_id", ""))
            dependencies[sid] = resolved_deps
            in_degree[sid] = len(resolved_deps)
            for dep_id in resolved_deps:
                if dep_id in dependents:
                    dependents[dep_id].append(sid)

        # Topological sort (Kahn's algorithm)
        queue = [sid for sid in step_ids if in_degree[sid] == 0]
        ordered: list[str] = []
        parallel_groups: list[list[str]] = []

        while queue:
            parallel_groups.append(sorted(queue))
            next_queue: list[str] = []
            for sid in queue:
                ordered.append(sid)
                for dep_sid in dependents.get(sid, []):
                    in_degree[dep_sid] -= 1
                    if in_degree[dep_sid] == 0:
                        next_queue.append(dep_sid)
            queue = next_queue

        return {
            "status": "success",
            "dependency_graph": {
                "steps_ordered": ordered,
                "dependencies": dependencies,
                "parallel_groups": parallel_groups,
            },
        }
    except Exception as exc:
        return {"status": "error", "dependency_graph": {}, "error": f"Dependency resolution failed: {exc}"}
