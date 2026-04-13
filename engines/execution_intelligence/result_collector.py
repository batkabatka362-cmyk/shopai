"""Execution Intelligence — result collector.

Collects execution results from all tasks, aggregates success/failure counts,
and builds a unified execution summary.

Model note: Would use Qwen for structured result aggregation.
"""
from __future__ import annotations

import copy
from typing import Any


def collect_results(
    execution_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Collect and aggregate execution results into a summary.

    Args:
        execution_results: List of ExecutionResult / ActionResult dicts
            from action_executor.

    Returns:
        Structured dict with executed, failed, results, and counts.
    """
    try:
        if not isinstance(execution_results, list):
            return {
                "status": "error",
                "executed": [],
                "failed": [],
                "results": [],
                "total": 0,
                "success_count": 0,
                "fail_count": 0,
                "partial_count": 0,
                "error": "execution_results must be a list",
            }

        safe_results = copy.deepcopy(execution_results)

        executed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        logs: list[str] = []

        success_count = 0
        fail_count = 0
        partial_count = 0

        for result in safe_results:
            task_id = result.get("task_id", "unknown")
            action_type = result.get("action_type", "unknown")
            status = result.get("status", "fail")
            error = result.get("error")
            elapsed = result.get("elapsed_seconds", 0.0)
            tool_used = result.get("tool_used", "unknown")

            summary_entry: dict[str, Any] = {
                "task_id": task_id,
                "type": action_type,
                "status": status,
            }

            result_entry: dict[str, Any] = {
                "task_id": task_id,
                "result": result.get("result", {}),
            }

            if status == "success":
                success_count += 1
                executed.append(summary_entry)
                logs.append(
                    f"Task {action_type} ({task_id}) executed successfully "
                    f"via {tool_used} in {elapsed:.3f}s"
                )
            elif status == "partial":
                partial_count += 1
                executed.append(summary_entry)
                logs.append(
                    f"Task {action_type} ({task_id}) partially completed "
                    f"via {tool_used} in {elapsed:.3f}s"
                )
            else:
                fail_count += 1
                failed.append(summary_entry)
                error_msg = error or "unknown error"
                logs.append(
                    f"Task {action_type} ({task_id}) FAILED "
                    f"via {tool_used}: {error_msg}"
                )

            results.append(result_entry)

        total = success_count + fail_count + partial_count

        return {
            "status": "success",
            "executed": executed,
            "failed": failed,
            "results": results,
            "total": total,
            "success_count": success_count,
            "fail_count": fail_count,
            "partial_count": partial_count,
            "logs": logs,
        }
    except Exception as exc:
        return {
            "status": "error",
            "executed": [],
            "failed": [],
            "results": [],
            "total": 0,
            "success_count": 0,
            "fail_count": 0,
            "partial_count": 0,
            "logs": [],
            "error": f"Result collection failed: {exc}",
        }
