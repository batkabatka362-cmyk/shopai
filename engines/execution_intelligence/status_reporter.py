"""Execution Intelligence — status reporter.

Generates execution status reports with logs, timing breakdowns,
and success rates.

Model note: Would use Qwen for structured report generation.
"""
from __future__ import annotations

import copy
from typing import Any


def generate_status_report(
    collected: dict[str, Any],
    execution_results: list[dict[str, Any]],
    total_elapsed_seconds: float,
) -> dict[str, Any]:
    """Generate a comprehensive status report from collected results.

    Args:
        collected: Output from result_collector.collect_results.
        execution_results: Raw execution results for timing analysis.
        total_elapsed_seconds: Total wall-clock time for the pipeline.

    Returns:
        Structured StatusReport dict.
    """
    try:
        safe_collected = copy.deepcopy(collected)
        safe_results = copy.deepcopy(execution_results)

        total_tasks = int(safe_collected.get("total", 0))
        succeeded = int(safe_collected.get("success_count", 0))
        failed = int(safe_collected.get("fail_count", 0))
        partial = int(safe_collected.get("partial_count", 0))
        logs = list(safe_collected.get("logs", []))

        # Compute success rate
        success_rate = 0.0
        if total_tasks > 0:
            success_rate = round((succeeded + partial * 0.5) / total_tasks, 4)

        # Determine overall status
        overall_status = _determine_overall_status(succeeded, failed, partial, total_tasks)

        # Compute timing breakdown
        timing = _compute_timing(safe_results, total_elapsed_seconds)

        # Add summary log entry
        logs.append(
            f"Execution complete: {succeeded} succeeded, {failed} failed, "
            f"{partial} partial out of {total_tasks} tasks "
            f"({success_rate:.1%} success rate, {total_elapsed_seconds:.3f}s total)"
        )

        return {
            "status": "success",
            "report": {
                "overall_status": overall_status,
                "success_rate": success_rate,
                "total_tasks": total_tasks,
                "succeeded": succeeded,
                "failed": failed,
                "partial": partial,
                "logs": logs,
                "elapsed_seconds": round(total_elapsed_seconds, 4),
                "timing": timing,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "report": {
                "overall_status": "fail",
                "success_rate": 0.0,
                "total_tasks": 0,
                "succeeded": 0,
                "failed": 0,
                "partial": 0,
                "logs": [f"Status report generation failed: {exc}"],
                "elapsed_seconds": round(total_elapsed_seconds, 4),
                "timing": {},
            },
        }


def _determine_overall_status(
    succeeded: int,
    failed: int,
    partial: int,
    total: int,
) -> str:
    """Determine the overall execution status.

    - "success" if all tasks succeeded
    - "partial" if some succeeded and some failed
    - "fail" if all tasks failed or no tasks ran
    """
    if total == 0:
        return "fail"
    if failed == 0 and partial == 0:
        return "success"
    if succeeded == 0 and partial == 0:
        return "fail"
    return "partial"


def _compute_timing(
    execution_results: list[dict[str, Any]],
    total_elapsed: float,
) -> dict[str, Any]:
    """Compute timing breakdown from individual task results."""
    if not execution_results:
        return {
            "total_elapsed_seconds": round(total_elapsed, 4),
            "avg_task_seconds": 0.0,
            "slowest_task_id": "",
            "slowest_task_seconds": 0.0,
            "fastest_task_id": "",
            "fastest_task_seconds": 0.0,
        }

    durations: list[tuple[str, float]] = []
    for result in execution_results:
        task_id = result.get("task_id", "unknown")
        elapsed = float(result.get("elapsed_seconds", 0.0))
        durations.append((task_id, elapsed))

    if not durations:
        return {
            "total_elapsed_seconds": round(total_elapsed, 4),
            "avg_task_seconds": 0.0,
            "slowest_task_id": "",
            "slowest_task_seconds": 0.0,
            "fastest_task_id": "",
            "fastest_task_seconds": 0.0,
        }

    total_task_time = sum(d for _, d in durations)
    avg_time = total_task_time / len(durations)

    slowest = max(durations, key=lambda x: x[1])
    fastest = min(durations, key=lambda x: x[1])

    return {
        "total_elapsed_seconds": round(total_elapsed, 4),
        "avg_task_seconds": round(avg_time, 4),
        "slowest_task_id": slowest[0],
        "slowest_task_seconds": round(slowest[1], 4),
        "fastest_task_id": fastest[0],
        "fastest_task_seconds": round(fastest[1], 4),
    }
