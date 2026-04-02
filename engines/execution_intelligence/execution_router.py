"""Execution Intelligence — execution router.

Routes validated tasks to the correct execution path based on tool selection.
Determines parallel vs sequential execution order by respecting dependencies
and execution mode (sync/async).

Model note: Would use Mistral for intelligent routing in complex dependency graphs.
"""
from __future__ import annotations

import copy
from typing import Any


def route_tasks(
    validated_tasks: list[dict[str, Any]],
    tool_selections: list[dict[str, Any]],
) -> dict[str, Any]:
    """Route tasks into ordered execution batches.

    Tasks with no unmet dependencies can run in parallel within a batch.
    Tasks with dependencies are scheduled after their prerequisites.

    Args:
        validated_tasks: List of ValidatedTask dicts.
        tool_selections: Matching list of ToolSelection dicts.

    Returns:
        Structured dict with ordered execution batches.
    """
    try:
        if not isinstance(validated_tasks, list) or not isinstance(tool_selections, list):
            return {
                "status": "error",
                "batches": [],
                "error": "Both validated_tasks and tool_selections must be lists",
            }

        safe_tasks = copy.deepcopy(validated_tasks)
        safe_selections = copy.deepcopy(tool_selections)

        # Build selection lookup by task_id
        selection_map: dict[str, dict[str, Any]] = {}
        for sel in safe_selections:
            selection_map[sel.get("task_id", "")] = sel

        # Build enriched task list with routing info
        routable_tasks = _enrich_with_routing(safe_tasks, selection_map)

        # Build execution batches respecting dependencies
        batches = _build_execution_batches(routable_tasks)

        # Generate execution plan
        plan = _build_execution_plan(batches)

        logs: list[str] = []
        for i, batch in enumerate(batches):
            task_ids = [t["task_id"] for t in batch]
            mode = "parallel" if len(batch) > 1 else "sequential"
            logs.append(
                f"Batch {i}: {mode} — {len(batch)} task(s): "
                f"{', '.join(task_ids)}"
            )

        return {
            "status": "success",
            "batches": batches,
            "execution_plan": plan,
            "total_batches": len(batches),
            "total_tasks": sum(len(b) for b in batches),
            "logs": logs,
        }
    except Exception as exc:
        return {
            "status": "error",
            "batches": [],
            "execution_plan": [],
            "total_batches": 0,
            "total_tasks": 0,
            "logs": [],
            "error": f"Routing failed: {exc}",
        }


def _enrich_with_routing(
    tasks: list[dict[str, Any]],
    selection_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach tool selection and routing metadata to each task."""
    enriched: list[dict[str, Any]] = []

    for task in tasks:
        task_id = task.get("task_id", "")
        selection = selection_map.get(task_id, {})

        enriched_task: dict[str, Any] = {
            "task_id": task_id,
            "action_type": task.get("action_type", ""),
            "parameters": task.get("parameters", {}),
            "priority": task.get("priority", 3),
            "dependencies": task.get("dependencies", []),
            "tool_name": selection.get("tool_name", "unknown"),
            "tool_config": selection.get("tool_config", {}),
            "execution_mode": selection.get("execution_mode", "sync"),
        }
        enriched.append(enriched_task)

    return enriched


def _build_execution_batches(
    tasks: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Build ordered batches using topological sort on dependencies.

    Tasks with satisfied dependencies are grouped into parallel batches.
    Within each batch, tasks are sorted by priority.

    Model note: Mistral would optimize batch ordering for throughput.
    """
    if not tasks:
        return []

    # Build dependency graph
    task_map: dict[str, dict[str, Any]] = {}
    for task in tasks:
        task_map[task["task_id"]] = task

    all_task_ids = set(task_map.keys())
    completed: set[str] = set()
    remaining = list(tasks)
    batches: list[list[dict[str, Any]]] = []

    # Guard against infinite loop from circular deps
    max_iterations = len(tasks) + 1
    iteration = 0

    while remaining and iteration < max_iterations:
        iteration += 1

        # Find tasks whose dependencies are all satisfied
        ready: list[dict[str, Any]] = []
        still_waiting: list[dict[str, Any]] = []

        for task in remaining:
            deps = task.get("dependencies", [])
            # Only consider deps that are in this batch (ignore external)
            relevant_deps = [d for d in deps if d in all_task_ids]
            unmet = [d for d in relevant_deps if d not in completed]

            if not unmet:
                ready.append(task)
            else:
                still_waiting.append(task)

        if not ready:
            # Circular dependency or unresolvable — force remaining into a batch
            ready = still_waiting
            still_waiting = []

        # Sort ready tasks by priority
        ready.sort(key=lambda t: t.get("priority", 3))
        batches.append(ready)

        for task in ready:
            completed.add(task["task_id"])

        remaining = still_waiting

    return batches


def _build_execution_plan(
    batches: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Build a human-readable execution plan from batches."""
    plan: list[dict[str, Any]] = []

    for batch_index, batch in enumerate(batches):
        batch_entry: dict[str, Any] = {
            "batch_index": batch_index,
            "mode": "parallel" if len(batch) > 1 else "sequential",
            "tasks": [],
        }

        for task in batch:
            batch_entry["tasks"].append({
                "task_id": task["task_id"],
                "action_type": task["action_type"],
                "tool_name": task.get("tool_name", "unknown"),
                "execution_mode": task.get("execution_mode", "sync"),
                "priority": task.get("priority", 3),
            })

        plan.append(batch_entry)

    return plan
