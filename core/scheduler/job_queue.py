"""JobQueue — priority queue for engine jobs."""
from __future__ import annotations

import heapq
import threading
import time
from typing import Any

from utils.helpers import generate_id


class JobQueue:
    """Thread-safe priority job queue."""

    def __init__(self, max_size: int = 10000) -> None:
        self._queue: list[tuple[int, float, dict]] = []  # (priority, timestamp, job)
        self._lock = threading.Lock()
        self._max_size = max_size
        self._stats = {"enqueued": 0, "dequeued": 0, "dropped": 0}

    def enqueue(self, engine_name: str, params: dict[str, Any], priority: int = 5) -> str:
        """Add job to queue. Priority 1=highest, 10=lowest."""
        job_id = generate_id("job")
        job = {
            "job_id": job_id,
            "engine": engine_name,
            "params": params,
            "priority": priority,
            "status": "queued",
            "created_at": time.time(),
        }
        with self._lock:
            if len(self._queue) >= self._max_size:
                self._stats["dropped"] += 1
                return ""
            heapq.heappush(self._queue, (priority, time.time(), job))
            self._stats["enqueued"] += 1
        return job_id

    def dequeue(self) -> dict[str, Any] | None:
        """Get highest priority job."""
        with self._lock:
            if not self._queue:
                return None
            _, _, job = heapq.heappop(self._queue)
            self._stats["dequeued"] += 1
            return job

    def peek(self) -> dict[str, Any] | None:
        """Look at next job without removing."""
        with self._lock:
            if not self._queue:
                return None
            return self._queue[0][2]

    def size(self) -> int:
        with self._lock:
            return len(self._queue)

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {**self._stats, "current_size": len(self._queue), "max_size": self._max_size}

    def clear(self) -> int:
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
            return count
