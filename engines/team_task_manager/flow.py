"""Team Task Manager Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Pending Actions -> Task Generator -> Workload Balancer ->
  Priority Ranker -> Deadline Tracker -> Output

Engine contract:
  Input:  {status, data: {pending_actions, team_members, current_workload}, meta, error}
  Output: {status, data: {tasks, workload_distribution, overdue_count}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .task_generator import generate_tasks
from .workload_balancer import balance_workload
from .priority_ranker import rank_priorities
from .deadline_tracker import track_deadlines


class TeamTaskManagerEngine:
    """Team Task Manager Engine — orchestrator only, no logic."""

    ENGINE_NAME = "team_task_manager"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full task management pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            Task management output dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation (no mutation) ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        pending_actions = data.get("pending_actions", [])
        team_members = data.get("team_members", [])
        current_workload = data.get("current_workload", {})

        if not pending_actions:
            return self._fail("Pending actions list is required", 0.0)

        # ---- Stage 1: Task Generator ----
        gen_result = generate_tasks(pending_actions=pending_actions)
        if gen_result.get("status") == "error":
            return self._fail(
                f"Task generation failed: {gen_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        tasks = gen_result.get("tasks", [])

        # ---- Stage 2: Workload Balancer ----
        balance_result = balance_workload(
            tasks=tasks,
            team_members=team_members,
            current_workload=current_workload,
        )
        if balance_result.get("status") == "error":
            return self._fail(
                f"Workload balancing failed: {balance_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        assigned_tasks = balance_result.get("assigned_tasks", [])
        workload_distribution = balance_result.get("workload_distribution", {})

        # ---- Stage 3: Priority Ranker ----
        rank_result = rank_priorities(tasks=assigned_tasks)
        if rank_result.get("status") == "error":
            return self._fail(
                f"Priority ranking failed: {rank_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        ranked_tasks = rank_result.get("ranked_tasks", [])

        # ---- Stage 4: Deadline Tracker ----
        deadline_result = track_deadlines(tasks=ranked_tasks)
        if deadline_result.get("status") == "error":
            return self._fail(
                f"Deadline tracking failed: {deadline_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        final_tasks = deadline_result.get("tracked_tasks", [])
        overdue_count = deadline_result.get("overdue_count", 0)

        # ---- Stage 5: Assemble output ----
        elapsed = time.monotonic() - start

        # Build final task list matching output contract
        output_tasks: list[dict[str, Any]] = []
        for t in final_tasks:
            output_tasks.append({
                "id": t.get("id", ""),
                "assignee": t.get("assignee", ""),
                "assignee_name": t.get("assignee_name", ""),
                "priority": t.get("priority", "P2"),
                "deadline": t.get("deadline", ""),
                "description": t.get("description", ""),
                "category": t.get("category", "general"),
                "deadline_status": t.get("deadline_status", "on_track"),
                "hours_remaining": t.get("hours_remaining", 0),
                "estimated_minutes": t.get("estimated_minutes", 0),
            })

        return {
            "status": "success",
            "data": {
                "tasks": output_tasks,
                "workload_distribution": workload_distribution,
                "overdue_count": overdue_count,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
