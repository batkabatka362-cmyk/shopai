"""Time Intelligence — retry scheduler.

Handles retry logic with exponential backoff, maximum retry limits,
and conditional retry decisions.

Model note: Would use LLaMA for complex retry strategy reasoning.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any


_DEFAULT_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 10.0
_BACKOFF_MULTIPLIER = 2.0
_MAX_BACKOFF_SECONDS = 600.0
_JITTER_FACTOR = 0.1

_NON_RETRYABLE_ERRORS = frozenset({
    "invalid_input",
    "permission_denied",
    "task_cancelled",
    "unsupported_type",
})


def schedule_retries(
    failed_tasks: list[dict[str, Any]],
    execution_statuses: dict[str, dict[str, Any]],
    current_time: str,
    max_retries: int = _DEFAULT_MAX_RETRIES,
) -> dict[str, Any]:
    """Compute retry schedules for failed tasks using exponential backoff.

    Args:
        failed_tasks: List of task status dicts with status == "failed".
        execution_statuses: Full status map for context.
        current_time: ISO timestamp of current time.
        max_retries: Maximum number of retry attempts allowed.

    Returns:
        Structured dict with retry info per task and tasks that are exhausted.
    """
    try:
        failed_tasks = copy.deepcopy(failed_tasks)
        current_dt = _parse_time(current_time)

        retries: list[dict[str, Any]] = []
        exhausted: list[dict[str, Any]] = []

        for task_info in failed_tasks:
            task_id = task_info.get("task_id", "")
            attempt = int(task_info.get("attempt", 1))
            error = task_info.get("error", "unknown")

            if not _is_retryable(error):
                exhausted.append({
                    "task_id": task_id,
                    "reason": f"non_retryable_error: {error}",
                    "attempts": attempt,
                })
                continue

            if attempt >= max_retries:
                exhausted.append({
                    "task_id": task_id,
                    "reason": "max_retries_exceeded",
                    "attempts": attempt,
                })
                continue

            backoff = _compute_backoff(attempt)
            next_retry_dt = current_dt + timedelta(seconds=backoff)

            retries.append({
                "task_id": task_id,
                "retry_count": attempt,
                "max_retries": max_retries,
                "next_retry_at": next_retry_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "backoff_seconds": round(backoff, 2),
                "reason": error,
            })

        return {
            "status": "success",
            "retries": retries,
            "exhausted": exhausted,
            "retry_count": len(retries),
            "exhausted_count": len(exhausted),
        }
    except Exception as exc:
        return {
            "status": "error",
            "retries": [],
            "exhausted": [],
            "retry_count": 0,
            "exhausted_count": 0,
            "error": str(exc),
        }


def _compute_backoff(attempt: int) -> float:
    """Compute exponential backoff with capped maximum.

    Formula: min(base * multiplier^(attempt-1), max_backoff)
    A small deterministic jitter is added based on attempt number.
    """
    raw = _BASE_BACKOFF_SECONDS * (_BACKOFF_MULTIPLIER ** (attempt - 1))
    capped = min(raw, _MAX_BACKOFF_SECONDS)
    jitter = capped * _JITTER_FACTOR * ((attempt % 3) / 3.0)
    return round(capped + jitter, 2)


def _is_retryable(error: str | None) -> bool:
    """Determine if an error is retryable."""
    if not error:
        return True
    normalized = error.strip().lower().replace(" ", "_")
    for non_retryable in _NON_RETRYABLE_ERRORS:
        if non_retryable in normalized:
            return False
    return True


def _parse_time(time_str: str) -> datetime:
    """Parse an ISO time string into a timezone-aware datetime."""
    return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
