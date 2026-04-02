"""Time Intelligence — queue manager.

Manages the execution queue: enqueue, dequeue, reorder by priority,
and enforce capacity limits.

Model note: Would use Qwen for queue optimization decisions.
"""
from __future__ import annotations

import copy
import heapq
import time
from typing import Any

_DEFAULT_CAPACITY = 50


class ExecutionQueue:
    """Priority-based execution queue with capacity management."""

    def __init__(self, capacity: int = _DEFAULT_CAPACITY) -> None:
        self._capacity = capacity
        self._heap: list[tuple[float, int, dict[str, Any]]] = []
        self._counter = 0
        self._task_ids: set[str] = set()

    @property
    def size(self) -> int:
        return len(self._heap)

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def remaining_capacity(self) -> int:
        return max(0, self._capacity - len(self._heap))

    def enqueue(self, entry: dict[str, Any]) -> bool:
        """Add a task to the queue. Returns False if at capacity."""
        task_id = entry.get("task_id", "")
        if task_id in self._task_ids:
            return False
        if self.size >= self._capacity:
            return False

        priority_score = float(entry.get("priority_score", 0.0))
        self._counter += 1
        heapq.heappush(
            self._heap,
            (-priority_score, self._counter, copy.deepcopy(entry)),
        )
        self._task_ids.add(task_id)
        return True

    def dequeue(self) -> dict[str, Any] | None:
        """Remove and return the highest-priority task."""
        while self._heap:
            neg_prio, _counter, entry = heapq.heappop(self._heap)
            task_id = entry.get("task_id", "")
            if task_id in self._task_ids:
                self._task_ids.discard(task_id)
                return entry
        return None

    def peek(self) -> dict[str, Any] | None:
        """Return the highest-priority task without removing it."""
        for neg_prio, _counter, entry in self._heap:
            if entry.get("task_id", "") in self._task_ids:
                return copy.deepcopy(entry)
        return None

    def remove(self, task_id: str) -> bool:
        """Mark a task as removed from the queue."""
        if task_id in self._task_ids:
            self._task_ids.discard(task_id)
            return True
        return False

    def contains(self, task_id: str) -> bool:
        return task_id in self._task_ids

    def get_all_entries(self) -> list[dict[str, Any]]:
        """Return all active entries sorted by priority (highest first)."""
        entries = []
        for neg_prio, _counter, entry in sorted(self._heap):
            if entry.get("task_id", "") in self._task_ids:
                entries.append(copy.deepcopy(entry))
        return entries

    def reorder(self) -> None:
        """Rebuild the heap to ensure correct ordering after mutations."""
        active = [
            (neg_prio, ctr, entry)
            for neg_prio, ctr, entry in self._heap
            if entry.get("task_id", "") in self._task_ids
        ]
        heapq.heapify(active)
        self._heap = active


def build_queue(
    scheduled_tasks: list[dict[str, Any]],
    blocked_task_ids: set[str],
    capacity: int = _DEFAULT_CAPACITY,
) -> dict[str, Any]:
    """Build an execution queue from scheduled tasks.

    Args:
        scheduled_tasks: Tasks from the scheduler stage.
        blocked_task_ids: Task IDs that should not be enqueued.
        capacity: Maximum queue capacity.

    Returns:
        Structured dict with queue entries, overflow info, and the queue object.
    """
    try:
        queue = ExecutionQueue(capacity=capacity)
        enqueued: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        for task in scheduled_tasks:
            task_id = task.get("task_id", "")
            if task_id in blocked_task_ids:
                rejected.append({
                    "task_id": task_id,
                    "reason": "blocked_dependency",
                })
                continue

            entry = {
                "task_id": task_id,
                "priority_score": task.get("priority_score", 0.0),
                "scheduled_time": task.get("scheduled_time", ""),
                "status": "queued",
                "enqueued_at": timestamp,
            }

            if queue.enqueue(entry):
                enqueued.append(copy.deepcopy(entry))
            else:
                rejected.append({
                    "task_id": task_id,
                    "reason": "capacity_exceeded" if queue.size >= queue.capacity else "duplicate",
                })

        return {
            "status": "success",
            "queue_entries": enqueued,
            "rejected": rejected,
            "queue_size": queue.size,
            "capacity_remaining": queue.remaining_capacity,
            "queue": queue,
        }
    except Exception as exc:
        return {
            "status": "error",
            "queue_entries": [],
            "rejected": [],
            "queue_size": 0,
            "capacity_remaining": capacity,
            "queue": ExecutionQueue(capacity=capacity),
            "error": str(exc),
        }
