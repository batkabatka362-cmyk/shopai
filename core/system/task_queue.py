"""TaskQueue — dependency-aware task execution system.

Tasks have dependencies. System executes in correct order.
No random execution — graph-based only.

Example:
    q = TaskQueue()
    q.add("analyze", engine="product_research", data={...})
    q.add("price", engine="pricing", depends_on=["analyze"])
    q.add("launch", engine="ads", depends_on=["price"])
    results = q.execute_all()  # analyze → price → launch
"""
from __future__ import annotations

import time
import threading
from enum import Enum
from typing import Any, Callable

from utils.logger import get_logger

logger = get_logger("task_queue")


class TaskStatus(Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class Task:
    """A single executable task with dependencies."""

    __slots__ = (
        "id", "engine", "action", "data", "depends_on", "status",
        "result", "error", "priority", "created_at", "started_at",
        "completed_at", "retries", "max_retries", "metadata",
    )

    def __init__(self, task_id: str, engine: str = "", action: str = "",
                 data: dict | None = None, depends_on: list[str] | None = None,
                 priority: int = 0, max_retries: int = 1,
                 metadata: dict | None = None) -> None:
        self.id = task_id
        self.engine = engine
        self.action = action
        self.data = data or {}
        self.depends_on = depends_on or []
        self.status = TaskStatus.PENDING
        self.result: dict[str, Any] | None = None
        self.error: str = ""
        self.priority = priority
        self.created_at = time.time()
        self.started_at: float = 0
        self.completed_at: float = 0
        self.retries = 0
        self.max_retries = max_retries
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "engine": self.engine, "action": self.action,
            "status": self.status.value, "depends_on": self.depends_on,
            "priority": self.priority, "error": self.error,
            "duration_s": round(self.completed_at - self.started_at, 3) if self.completed_at else 0,
        }


class TaskQueue:
    """Dependency-aware task queue with graph-based execution."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._execution_order: list[str] = []
        self._lock = threading.Lock()

    # ── Add Tasks ────────────────────────────────────────────

    def add(self, task_id: str, engine: str = "", action: str = "",
            data: dict | None = None, depends_on: list[str] | None = None,
            priority: int = 0, max_retries: int = 1,
            metadata: dict | None = None) -> Task:
        """Add a task to the queue."""
        task = Task(task_id, engine, action, data, depends_on, priority, max_retries, metadata)
        with self._lock:
            self._tasks[task_id] = task
            self._execution_order = []  # Invalidate cached order
        return task

    def add_chain(self, tasks: list[dict[str, Any]]) -> list[Task]:
        """Add a chain of tasks where each depends on the previous."""
        created = []
        prev_id = ""
        for t in tasks:
            depends = [prev_id] if prev_id else t.get("depends_on", [])
            task = self.add(
                t["id"], engine=t.get("engine", ""), action=t.get("action", ""),
                data=t.get("data"), depends_on=depends,
                priority=t.get("priority", 0), metadata=t.get("metadata"),
            )
            created.append(task)
            prev_id = task.id
        return created

    # ── Dependency Graph ─────────────────────────────────────

    def get_execution_order(self) -> list[str]:
        """Topological sort — returns tasks in dependency-safe order."""
        if self._execution_order:
            return self._execution_order

        visited: set[str] = set()
        order: list[str] = []
        visiting: set[str] = set()  # Cycle detection

        def dfs(task_id: str) -> None:
            if task_id in visited:
                return
            if task_id in visiting:
                raise ValueError(f"Circular dependency detected: {task_id}")
            visiting.add(task_id)
            task = self._tasks.get(task_id)
            if task:
                for dep in task.depends_on:
                    if dep in self._tasks:
                        dfs(dep)
            visiting.discard(task_id)
            visited.add(task_id)
            order.append(task_id)

        # Sort by priority first, then topological
        sorted_ids = sorted(self._tasks.keys(),
                           key=lambda x: self._tasks[x].priority, reverse=True)
        for tid in sorted_ids:
            dfs(tid)

        self._execution_order = order
        return order

    def get_ready_tasks(self) -> list[Task]:
        """Get tasks whose dependencies are all completed."""
        ready = []
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            deps_met = all(
                self._tasks[d].status == TaskStatus.COMPLETED
                for d in task.depends_on if d in self._tasks
            )
            deps_failed = any(
                self._tasks[d].status == TaskStatus.FAILED
                for d in task.depends_on if d in self._tasks
            )
            if deps_failed:
                task.status = TaskStatus.BLOCKED
                task.error = "Dependency failed"
            elif deps_met:
                ready.append(task)
        return sorted(ready, key=lambda t: t.priority, reverse=True)

    def get_blocked_tasks(self) -> list[Task]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.BLOCKED]

    # ── Execution ────────────────────────────────────────────

    def execute_all(self, executor: Callable | None = None) -> dict[str, Any]:
        """Execute all tasks in dependency order."""
        if executor is None:
            executor = self._default_executor

        order = self.get_execution_order()
        start = time.monotonic()
        results: dict[str, Any] = {}

        for task_id in order:
            task = self._tasks[task_id]
            if task.status in (TaskStatus.BLOCKED, TaskStatus.SKIPPED):
                results[task_id] = task.to_dict()
                continue

            # Check dependencies
            deps_ok = all(
                self._tasks[d].status == TaskStatus.COMPLETED
                for d in task.depends_on if d in self._tasks
            )
            if not deps_ok:
                task.status = TaskStatus.BLOCKED
                task.error = "Dependency not met"
                results[task_id] = task.to_dict()
                continue

            # Inject dependency results into task data
            for dep_id in task.depends_on:
                dep = self._tasks.get(dep_id)
                if dep and dep.result:
                    task.data[f"_dep_{dep_id}"] = dep.result

            # Execute with retry
            self._execute_task(task, executor)
            results[task_id] = task.to_dict()

        elapsed = time.monotonic() - start
        completed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED)

        return {
            "total": len(self._tasks),
            "completed": completed,
            "failed": failed,
            "blocked": len(self.get_blocked_tasks()),
            "duration_s": round(elapsed, 3),
            "tasks": results,
            "execution_order": order,
        }

    def _execute_task(self, task: Task, executor: Callable) -> None:
        """Execute a single task with retry."""
        task.started_at = time.monotonic()
        task.status = TaskStatus.RUNNING

        for attempt in range(task.max_retries):
            try:
                task.retries = attempt
                result = executor(task)
                task.result = result if isinstance(result, dict) else {"output": result}
                task.status = TaskStatus.COMPLETED
                task.completed_at = time.monotonic()
                logger.info("Task %s completed (%.2fs)", task.id,
                           task.completed_at - task.started_at)
                return
            except Exception as exc:
                task.error = str(exc)
                if attempt < task.max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))

        task.status = TaskStatus.FAILED
        task.completed_at = time.monotonic()
        logger.warning("Task %s failed after %d attempts: %s",
                      task.id, task.max_retries, task.error)

    def _default_executor(self, task: Task) -> dict[str, Any]:
        """Default executor — runs engine via registry."""
        if not task.engine:
            return {"status": "skipped", "reason": "no engine specified"}

        from engines.registry import get_engine
        engine = get_engine(task.engine)
        if not engine:
            raise ValueError(f"Engine not found: {task.engine}")

        return engine.run(task.data)

    # ── Query ────────────────────────────────────────────────

    def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self._tasks.values()]

    def get_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for t in self._tasks.values():
            counts[t.status.value] = counts.get(t.status.value, 0) + 1
        return counts

    def clear(self) -> None:
        with self._lock:
            self._tasks.clear()
            self._execution_order.clear()
