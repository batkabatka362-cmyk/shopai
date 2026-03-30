"""TaskExecutor — executes individual tasks with retry, timeout, and history.

Uses only the Python standard library (threading for parallel execution
and timeout enforcement).
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

# Thread-safe in-process execution history store
_history_lock = threading.Lock()
_execution_history: list[dict[str, Any]] = []

# Task type → handler registry (populated by _register_builtin_handlers)
_TASK_HANDLERS: dict[str, Any] = {}


def _register_builtin_handlers() -> None:
    """Register default handlers for well-known task types."""
    def _noop_handler(task: dict[str, Any]) -> dict[str, Any]:
        return {"type": task.get("type"), "config": task.get("config", {})}

    def _log_handler(task: dict[str, Any]) -> dict[str, Any]:
        message = task.get("config", {}).get("message", "")
        return {"logged": message, "timestamp": datetime.now(timezone.utc).isoformat()}

    def _http_handler(task: dict[str, Any]) -> dict[str, Any]:
        import json
        import urllib.request

        cfg = task.get("config", {})
        url = cfg.get("url", "")
        method = cfg.get("method", "GET").upper()
        headers = cfg.get("headers", {})
        body = cfg.get("body")
        data = json.dumps(body).encode() if body is not None else None
        if data:
            headers = {**headers, "Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_body = resp.read().decode("utf-8")
        return {"status_code": resp.status, "body": response_body}

    _TASK_HANDLERS["noop"] = _noop_handler
    _TASK_HANDLERS["log"] = _log_handler
    _TASK_HANDLERS["http"] = _http_handler
    _TASK_HANDLERS["generic"] = _noop_handler


_register_builtin_handlers()


class TaskExecutor:
    """Execute tasks with configurable retry, timeout, and parallel batching."""

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a single task.

        Args:
            task: Dict with keys:
                  - ``type`` (str)          — task type name.
                  - ``config`` (dict)        — task-specific configuration.
                  - ``retry_count`` (int)    — max extra attempts on failure
                                              (0 = no retry).
                  - ``timeout`` (int)        — seconds before the task is
                                              considered failed (0 = no limit).
                  - ``id`` (str, optional)   — caller-supplied task ID.

        Returns:
            ``{"task_id": str, "status": "completed"|"failed",
               "result": any, "error": str|None,
               "duration_s": float, "timestamp": str}``
        """
        task_id = task.get("id") or str(uuid.uuid4())
        retry_count = int(task.get("retry_count", 0))
        timeout = int(task.get("timeout", 0))

        start = time.monotonic()
        if retry_count > 0:
            result = self.retry(
                {**task, "id": task_id}, max_attempts=retry_count + 1
            )
        elif timeout > 0:
            result = self._execute_with_timeout({**task, "id": task_id}, timeout)
        else:
            result = self._run_task({**task, "id": task_id})

        duration = round(time.monotonic() - start, 3)
        result.setdefault("task_id", task_id)
        result["duration_s"] = duration
        result.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

        self._record_result(task_id, result, duration)
        return result

    def execute_batch(
        self,
        tasks: list[dict[str, Any]],
        max_parallel: int = 5,
    ) -> list[dict[str, Any]]:
        """Execute a list of tasks in parallel.

        Args:
            tasks:        List of task dicts (same shape as :meth:`execute`).
            max_parallel: Maximum concurrent threads (default 5).

        Returns:
            List of result dicts in the same order as *tasks*.
        """
        results: list[dict[str, Any]] = [{}] * len(tasks)
        workers = min(max_parallel, len(tasks)) if tasks else 1

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_idx = {
                pool.submit(self.execute, task): idx
                for idx, task in enumerate(tasks)
            }
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    task_id = tasks[idx].get("id", str(uuid.uuid4()))
                    results[idx] = {
                        "task_id": task_id,
                        "status": "failed",
                        "error": str(exc),
                        "result": None,
                        "duration_s": 0.0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

        return results

    def retry(
        self, task: dict[str, Any], max_attempts: int = 3
    ) -> dict[str, Any]:
        """Attempt to execute *task* up to *max_attempts* times.

        Uses exponential back-off (1 s, 2 s, 4 s, …) between attempts.

        Returns:
            Result of the first successful attempt, or the last failure.
        """
        task_id = task.get("id") or str(uuid.uuid4())
        last_result: dict[str, Any] = {}
        delay = 1.0

        for attempt in range(1, max_attempts + 1):
            result = self._run_task({**task, "id": task_id})
            if result.get("status") == "completed":
                result["attempts"] = attempt
                return result
            last_result = result
            if attempt < max_attempts:
                time.sleep(delay)
                delay *= 2

        last_result["attempts"] = max_attempts
        return last_result

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _execute_with_timeout(
        self, task: dict[str, Any], timeout: int
    ) -> dict[str, Any]:
        """Run *task* in a thread, enforcing *timeout* seconds.

        If the task does not complete in time the result has
        ``status="failed"`` and ``error="timeout"``.
        """
        result_holder: list[dict[str, Any]] = []
        exc_holder: list[Exception] = []

        def _run() -> None:
            try:
                result_holder.append(self._run_task(task))
            except Exception as exc:
                exc_holder.append(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            return {
                "task_id": task.get("id", ""),
                "status": "failed",
                "error": f"Task timed out after {timeout} seconds.",
                "result": None,
            }

        if exc_holder:
            return {
                "task_id": task.get("id", ""),
                "status": "failed",
                "error": str(exc_holder[0]),
                "result": None,
            }

        return result_holder[0] if result_holder else {
            "task_id": task.get("id", ""),
            "status": "failed",
            "error": "No result returned.",
            "result": None,
        }

    def _run_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Dispatch to the registered handler for *task['type']*."""
        task_type = task.get("type", "generic")
        task_id = task.get("id", str(uuid.uuid4()))
        handler = _TASK_HANDLERS.get(task_type, _TASK_HANDLERS.get("generic"))

        if handler is None:
            return {
                "task_id": task_id,
                "status": "failed",
                "error": f"No handler registered for task type '{task_type}'.",
                "result": None,
            }

        try:
            output = handler(task)
            return {
                "task_id": task_id,
                "status": "completed",
                "result": output,
                "error": None,
            }
        except Exception as exc:
            return {
                "task_id": task_id,
                "status": "failed",
                "result": None,
                "error": str(exc),
            }

    def _record_result(
        self, task_id: str, result: dict[str, Any], duration: float
    ) -> None:
        """Append an execution record to the in-process history store."""
        record = {
            "task_id": task_id,
            "status": result.get("status"),
            "duration_s": duration,
            "timestamp": result.get(
                "timestamp", datetime.now(timezone.utc).isoformat()
            ),
            "error": result.get("error"),
        }
        with _history_lock:
            _execution_history.append(record)
            # Keep only the last 10 000 records to avoid unbounded growth
            if len(_execution_history) > 10_000:
                del _execution_history[:-10_000]

    def get_execution_history(
        self, task_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return recorded execution results.

        Args:
            task_id: If given, filter to records for this task ID only.

        Returns:
            List of history record dicts, newest last.
        """
        with _history_lock:
            records = list(_execution_history)
        if task_id is not None:
            records = [r for r in records if r.get("task_id") == task_id]
        return records

    # ------------------------------------------------------------------ #
    # Handler registration                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def register_handler(task_type: str, handler) -> None:
        """Register a custom handler function for a task type.

        Args:
            task_type: String key used in task dicts.
            handler:   Callable ``(task: dict) -> dict``.
        """
        _TASK_HANDLERS[task_type] = handler
