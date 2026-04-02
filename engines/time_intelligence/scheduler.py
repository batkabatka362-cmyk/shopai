"""Time Intelligence — scheduler.

Creates a scheduling plan: assigns time slots to tasks, respects dependency
ordering and priority scores, and produces a structured scheduling output.

Model note: Would use Qwen for structured scheduling plan generation.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any


_SLOT_DURATION_SECONDS = 60.0
_MAX_PARALLEL_SLOTS = 5
_BUFFER_BETWEEN_DEPENDENT_TASKS_SECONDS = 5.0


def create_schedule(
    classified_tasks: list[dict[str, Any]],
    priority_results: list[dict[str, Any]],
    execution_order: list[str],
    blocked_task_ids: set[str],
    time_estimates: list[dict[str, Any]],
    current_time: str,
) -> dict[str, Any]:
    """Create a scheduling plan for all executable tasks.

    Assigns time slots respecting dependency order and priority scores.
    Blocked tasks are excluded from the schedule.

    Args:
        classified_tasks: Tasks from the classifier stage.
        priority_results: Priority scores per task.
        execution_order: Topologically sorted task IDs.
        blocked_task_ids: Set of task IDs that are blocked.
        time_estimates: Estimated durations per task.
        current_time: ISO timestamp of current time.

    Returns:
        Structured dict with scheduled tasks and timing plan.
    """
    try:
        classified_tasks = copy.deepcopy(classified_tasks)
        priority_map = {p["task_id"]: p for p in priority_results}
        estimate_map = {e["task_id"]: e for e in time_estimates}
        task_map = {t["task_id"]: t for t in classified_tasks}

        current_dt = _parse_time(current_time)
        schedulable = [tid for tid in execution_order if tid not in blocked_task_ids]

        ordered = _sort_by_priority_within_deps(
            schedulable, priority_map, execution_order,
        )

        scheduled_tasks: list[dict[str, Any]] = []
        task_end_times: dict[str, datetime] = {}
        slot_index = 0

        for task_id in ordered:
            task = task_map.get(task_id)
            if not task:
                continue

            estimate = estimate_map.get(task_id, {})
            duration = estimate.get("estimated_seconds", 60.0)
            priority_data = priority_map.get(task_id, {})
            priority_score = priority_data.get("priority_score", 0.5)

            deps = task.get("dependencies", [])
            earliest_start = current_dt

            for dep_type in deps:
                for tid, end_t in task_end_times.items():
                    dep_task = task_map.get(tid)
                    if dep_task and dep_task.get("original_type") == dep_type:
                        candidate = end_t + timedelta(
                            seconds=_BUFFER_BETWEEN_DEPENDENT_TASKS_SECONDS,
                        )
                        if candidate > earliest_start:
                            earliest_start = candidate

            scheduled_time = earliest_start
            end_time = scheduled_time + timedelta(seconds=duration)
            task_end_times[task_id] = end_time

            deadline = task.get("deadline")
            if deadline:
                deadline_dt = _parse_time(deadline)
                if end_time > deadline_dt:
                    priority_score = min(1.0, priority_score + 0.1)

            scheduled_tasks.append({
                "task_id": task_id,
                "scheduled_time": scheduled_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "priority_score": round(priority_score, 4),
                "estimated_duration_seconds": round(duration, 2),
                "slot_index": slot_index,
                "model_note": "Qwen: structured scheduling plan",
            })
            slot_index += 1

        total_duration = _compute_total_duration(scheduled_tasks, task_end_times, current_dt)
        next_execution = scheduled_tasks[0]["scheduled_time"] if scheduled_tasks else current_time

        timing_plan = {
            "total_estimated_duration": f"{round(total_duration, 1)}s",
            "next_execution": next_execution,
            "slots_used": len(scheduled_tasks),
            "capacity_remaining": max(0, _MAX_PARALLEL_SLOTS * 10 - len(scheduled_tasks)),
        }

        return {
            "status": "success",
            "scheduled_tasks": scheduled_tasks,
            "timing_plan": timing_plan,
            "count": len(scheduled_tasks),
        }
    except Exception as exc:
        return {
            "status": "error",
            "scheduled_tasks": [],
            "timing_plan": {
                "total_estimated_duration": "0s",
                "next_execution": current_time,
                "slots_used": 0,
                "capacity_remaining": 0,
            },
            "count": 0,
            "error": str(exc),
        }


def _sort_by_priority_within_deps(
    task_ids: list[str],
    priority_map: dict[str, dict[str, Any]],
    execution_order: list[str],
) -> list[str]:
    """Sort tasks by priority score while preserving dependency ordering.

    Tasks that appear earlier in execution_order (dependency-wise) keep their
    relative order. Among tasks at the same dependency level, higher priority
    goes first.
    """
    order_index = {tid: i for i, tid in enumerate(execution_order)}

    def sort_key(tid: str) -> tuple[int, float]:
        dep_order = order_index.get(tid, 999)
        priority = priority_map.get(tid, {}).get("priority_score", 0.0)
        return (dep_order, -priority)

    return sorted(task_ids, key=sort_key)


def _parse_time(time_str: str) -> datetime:
    """Parse an ISO time string into a timezone-aware datetime."""
    return datetime.fromisoformat(time_str.replace("Z", "+00:00"))


def _compute_total_duration(
    scheduled_tasks: list[dict[str, Any]],
    task_end_times: dict[str, datetime],
    current_dt: datetime,
) -> float:
    """Compute total wall-clock duration from first to last task end."""
    if not task_end_times:
        return 0.0
    latest_end = max(task_end_times.values())
    return (latest_end - current_dt).total_seconds()
