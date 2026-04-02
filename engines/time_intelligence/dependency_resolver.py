"""Time Intelligence — dependency resolver.

Resolves task dependencies, builds a directed acyclic graph (DAG),
performs topological sort, and identifies blocked tasks.

Model note: Would use Mistral for dependency reasoning.
"""
from __future__ import annotations

import copy
from collections import deque
from typing import Any


def resolve_dependencies(
    classified_tasks: list[dict[str, Any]],
    completed_tasks: list[str],
) -> dict[str, Any]:
    """Resolve dependencies across all tasks and produce execution order.

    Builds a DAG from task dependencies, performs topological sort using
    Kahn's algorithm, and identifies blocked tasks whose dependencies
    are neither completed nor present in the current task set.

    Args:
        classified_tasks: Tasks from the classifier stage.
        completed_tasks: List of already-completed task type strings.

    Returns:
        Structured dict with execution order, blocked/ready tasks, and graph.
    """
    try:
        classified_tasks = copy.deepcopy(classified_tasks)
        completed_set = set(completed_tasks)

        task_map: dict[str, dict[str, Any]] = {}
        type_to_id: dict[str, str] = {}
        for task in classified_tasks:
            task_map[task["task_id"]] = task
            type_to_id[task["original_type"]] = task["task_id"]

        graph: dict[str, list[str]] = {t["task_id"]: [] for t in classified_tasks}
        in_degree: dict[str, int] = {t["task_id"]: 0 for t in classified_tasks}

        blocked_tasks: list[dict[str, Any]] = []
        unresolvable: set[str] = set()

        for task in classified_tasks:
            task_id = task["task_id"]
            deps = task.get("dependencies", [])
            missing_deps = []

            for dep in deps:
                if dep in completed_set:
                    continue

                dep_task_id = type_to_id.get(dep)
                if dep_task_id and dep_task_id in graph:
                    graph[dep_task_id].append(task_id)
                    in_degree[task_id] = in_degree.get(task_id, 0) + 1
                else:
                    missing_deps.append(dep)

            if missing_deps:
                unresolvable.add(task_id)
                blocked_tasks.append({
                    "task_id": task_id,
                    "blocked_by": missing_deps,
                    "reason": "unresolved_dependency",
                })

        cycle_ids = _detect_cycle(graph, in_degree)
        if cycle_ids:
            for cid in cycle_ids:
                if cid not in unresolvable:
                    unresolvable.add(cid)
                    blocked_tasks.append({
                        "task_id": cid,
                        "blocked_by": ["circular_dependency"],
                        "reason": "circular_dependency",
                    })

        execution_order = _topological_sort(graph, in_degree, unresolvable)

        ready_tasks = []
        for tid in execution_order:
            if tid not in unresolvable and in_degree.get(tid, 0) == 0:
                task_deps = task_map[tid].get("dependencies", [])
                all_resolved = all(
                    d in completed_set or type_to_id.get(d) in unresolvable is False
                    for d in task_deps
                )
                if all_resolved or not task_deps:
                    ready_tasks.append(tid)

        if not ready_tasks and execution_order:
            ready_tasks = [execution_order[0]]

        serializable_graph = {k: list(v) for k, v in graph.items()}

        return {
            "status": "success",
            "execution_order": execution_order,
            "blocked_tasks": blocked_tasks,
            "ready_tasks": ready_tasks,
            "dependency_graph": serializable_graph,
            "model_note": "Mistral: dependency graph reasoning",
        }
    except Exception as exc:
        task_ids = [t.get("task_id", "unknown") for t in classified_tasks]
        return {
            "status": "error",
            "execution_order": task_ids,
            "blocked_tasks": [],
            "ready_tasks": task_ids[:1],
            "dependency_graph": {},
            "error": str(exc),
            "model_note": "Mistral: dependency graph reasoning (fallback)",
        }


def _topological_sort(
    graph: dict[str, list[str]],
    in_degree: dict[str, int],
    excluded: set[str],
) -> list[str]:
    """Kahn's algorithm for topological sorting, excluding blocked nodes."""
    in_deg = dict(in_degree)
    queue: deque[str] = deque()

    for node in graph:
        if node not in excluded and in_deg.get(node, 0) == 0:
            queue.append(node)

    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for neighbor in graph.get(node, []):
            if neighbor in excluded:
                continue
            in_deg[neighbor] = in_deg.get(neighbor, 1) - 1
            if in_deg[neighbor] == 0:
                queue.append(neighbor)

    return order


def _detect_cycle(
    graph: dict[str, list[str]],
    in_degree: dict[str, int],
) -> list[str]:
    """Detect cycles in the graph using Kahn's algorithm residual check."""
    in_deg = dict(in_degree)
    queue: deque[str] = deque()

    for node in graph:
        if in_deg.get(node, 0) == 0:
            queue.append(node)

    visited_count = 0
    while queue:
        node = queue.popleft()
        visited_count += 1
        for neighbor in graph.get(node, []):
            in_deg[neighbor] = in_deg.get(neighbor, 1) - 1
            if in_deg[neighbor] == 0:
                queue.append(neighbor)

    if visited_count == len(graph):
        return []

    return [node for node in graph if in_deg.get(node, 0) > 0]
