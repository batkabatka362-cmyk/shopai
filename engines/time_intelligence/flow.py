"""Time Intelligence — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Task Classifier → Priority Analyzer → Dependency Resolver →
  Time Estimator → Scheduler → Queue Manager → Execution Trigger →
  Delay Handler → Retry Scheduler → Status Tracker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {tasks, completed_tasks, current_time}, meta, error}
  Output: {status, data: {scheduled_tasks, delayed_tasks, blocked_tasks,
           execution_order, timing_plan}, meta: {engine, ...}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .task_classifier import classify_tasks
from .priority_analyzer import analyze_priorities
from .dependency_resolver import resolve_dependencies
from .time_estimator import estimate_times
from .scheduler import create_schedule
from .queue_manager import build_queue
from .execution_trigger import trigger_ready_tasks
from .status_tracker import build_initial_statuses
from .retry_scheduler import schedule_retries
from .delay_handler import compute_delays
from .memory_reader import read_past_schedules, compute_input_hash
from .memory_writer import write_schedule_result


class TimeIntelligenceEngine:
    """Time Intelligence Engine — orchestrator only, no logic."""

    ENGINE_NAME = "time_intelligence"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full time intelligence pipeline.

        Args:
            input_payload: TimeIntelligenceInput dict.

        Returns:
            TimeIntelligenceOutput dict.
        """
        start = time.monotonic()

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

        tasks = data.get("tasks", [])
        if not tasks or not isinstance(tasks, list):
            return self._fail("tasks is required and must be a non-empty list", 0.0)

        completed_tasks = list(data.get("completed_tasks", []))
        current_time = str(data.get("current_time", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))

        input_hash = compute_input_hash(data)
        task_types = list({str(t.get("type", "unknown")) for t in tasks})
        _past = read_past_schedules(task_types=task_types, limit=5)
        past_records = _past.get("records", [])

        classify_result = classify_tasks(
            tasks=tasks,
            current_time=current_time,
        )
        if classify_result.get("status") == "error":
            return self._fail(
                f"Classification failed: {classify_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        classified_tasks = classify_result.get("classified_tasks", [])
        if not classified_tasks:
            return self._fail("No tasks classified", time.monotonic() - start)

        priority_result = analyze_priorities(
            classified_tasks=classified_tasks,
            completed_tasks=completed_tasks,
            current_time=current_time,
        )
        if priority_result.get("status") == "error":
            return self._fail(
                f"Priority analysis failed: {priority_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        priority_results = priority_result.get("priority_results", [])

        dep_result = resolve_dependencies(
            classified_tasks=classified_tasks,
            completed_tasks=completed_tasks,
        )
        execution_order = dep_result.get("execution_order", [])
        blocked_tasks = dep_result.get("blocked_tasks", [])
        ready_tasks = dep_result.get("ready_tasks", [])
        blocked_ids = {b["task_id"] for b in blocked_tasks}

        time_result = estimate_times(
            classified_tasks=classified_tasks,
            priority_results=priority_results,
            past_records=past_records,
        )
        if time_result.get("status") == "error":
            return self._fail(
                f"Time estimation failed: {time_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        time_estimates = time_result.get("estimates", [])

        schedule_result = create_schedule(
            classified_tasks=classified_tasks,
            priority_results=priority_results,
            execution_order=execution_order,
            blocked_task_ids=blocked_ids,
            time_estimates=time_estimates,
            current_time=current_time,
        )
        if schedule_result.get("status") == "error":
            return self._fail(
                f"Scheduling failed: {schedule_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        scheduled_tasks = schedule_result.get("scheduled_tasks", [])
        timing_plan = schedule_result.get("timing_plan", {})

        queue_result = build_queue(
            scheduled_tasks=scheduled_tasks,
            blocked_task_ids=blocked_ids,
        )
        queue_entries = queue_result.get("queue_entries", [])

        trigger_result = trigger_ready_tasks(
            queue_entries=queue_entries,
            ready_task_ids=ready_tasks,
            blocked_task_ids=blocked_ids,
            execution_statuses={},
            current_time=current_time,
        )
        triggered = trigger_result.get("triggered", [])
        triggered_ids = {t["task_id"] for t in triggered}

        delay_result = compute_delays(
            classified_tasks=classified_tasks,
            triggered_tasks=triggered,
            execution_order=execution_order,
            current_time=current_time,
        )
        delayed_tasks = delay_result.get("delayed_tasks", [])

        queue_entry_ids = {e["task_id"] for e in queue_entries}
        status_result = build_initial_statuses(
            classified_tasks=classified_tasks,
            blocked_task_ids=blocked_ids,
            queue_entry_ids=queue_entry_ids,
            triggered_ids=triggered_ids,
        )
        tracker = status_result.get("tracker")
        all_statuses = tracker.get_all() if tracker else {}

        failed_statuses = [
            s for s in all_statuses.values()
            if s.get("status") == "failed"
        ]
        retry_result = schedule_retries(
            failed_tasks=failed_statuses,
            execution_statuses=all_statuses,
            current_time=current_time,
        )
        retry_infos = retry_result.get("retries", [])

        delayed_with_retries = list(delayed_tasks)
        for retry in retry_infos:
            delayed_with_retries.append({
                "task_id": retry["task_id"],
                "reason": f"retry #{retry['retry_count']}: {retry['reason']}",
                "retry_at": retry["next_retry_at"],
            })

        _write_result = write_schedule_result(
            input_hash=input_hash,
            scheduled_tasks=scheduled_tasks,
            blocked_tasks=blocked_tasks,
            delayed_tasks=delayed_with_retries,
            execution_order=execution_order,
            timing_plan=timing_plan,
            task_types=task_types,
            elapsed_seconds=time.monotonic() - start,
        )

        elapsed = time.monotonic() - start

        output_scheduled = [
            {
                "task_id": t["task_id"],
                "scheduled_time": t["scheduled_time"],
                "priority_score": t["priority_score"],
            }
            for t in scheduled_tasks
        ]

        output_blocked = [
            {
                "task_id": b["task_id"],
                "blocked_by": b.get("blocked_by", []),
            }
            for b in blocked_tasks
        ]

        output_delayed = [
            {
                "task_id": d.get("task_id", ""),
                "reason": d.get("reason", ""),
                "retry_at": d.get("retry_at", d.get("resume_at", "")),
            }
            for d in delayed_with_retries
        ]

        return {
            "status": "scheduled",
            "data": {
                "scheduled_tasks": output_scheduled,
                "delayed_tasks": output_delayed,
                "blocked_tasks": output_blocked,
                "execution_order": execution_order,
                "timing_plan": timing_plan,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

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
