"""Execution Intelligence — retry handler.

Handles failed task retries with exponential backoff, max retry limits,
and retry condition evaluation.

Model note: Would use Mistral for intelligent retry decisions.
"""
from __future__ import annotations

import copy
import time
from typing import Any


# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

_DEFAULT_MAX_RETRIES = 3
_BASE_DELAY_SECONDS = 1.0
_MAX_DELAY_SECONDS = 30.0
_BACKOFF_MULTIPLIER = 2.0
_JITTER_FACTOR = 0.1  # 10% jitter range

# Action types with custom retry limits
_ACTION_RETRY_LIMITS: dict[str, int] = {
    "launch_ad": 2,         # Ads APIs are often eventually consistent
    "send_email": 2,        # Emails: limited retries to avoid duplicates
    "update_inventory": 3,  # Inventory: important, retry more
    "create_product": 3,
    "generate_content": 2,  # Content gen: expensive, fewer retries
}


def build_retry_state(
    task_id: str,
    action_type: str = "",
) -> dict[str, Any]:
    """Create initial retry state for a task.

    Args:
        task_id: The task identifier.
        action_type: The action type (used for custom retry limits).

    Returns:
        RetryInfo dict with initial state.
    """
    max_retries = _ACTION_RETRY_LIMITS.get(action_type, _DEFAULT_MAX_RETRIES)

    return {
        "task_id": task_id,
        "attempts": 0,
        "max_retries": max_retries,
        "last_error": "",
        "next_delay_seconds": _BASE_DELAY_SECONDS,
        "exhausted": False,
    }


def should_retry(
    retry_state: dict[str, Any],
    error_classification: dict[str, Any],
) -> bool:
    """Determine if a task should be retried.

    Args:
        retry_state: Current retry state for the task.
        error_classification: Error classification from error_handler.

    Returns:
        True if the task should be retried, False otherwise.
    """
    try:
        if retry_state.get("exhausted", False):
            return False

        attempts = int(retry_state.get("attempts", 0))
        max_retries = int(retry_state.get("max_retries", _DEFAULT_MAX_RETRIES))

        if attempts >= max_retries:
            return False

        recoverable = error_classification.get("recoverable", False)
        if not recoverable:
            return False

        strategy = error_classification.get("recovery_strategy", "skip")
        if strategy in ("abort", "skip"):
            return False

        return True
    except Exception:
        return False


def record_attempt(
    retry_state: dict[str, Any],
    error_message: str,
) -> dict[str, Any]:
    """Record a retry attempt and compute the next delay.

    Uses exponential backoff: delay = base * multiplier^attempts, capped at max.

    Args:
        retry_state: Current retry state (not mutated).
        error_message: Error from the latest attempt.

    Returns:
        Updated retry state dict (new copy).
    """
    try:
        state = copy.deepcopy(retry_state)
        attempts = int(state.get("attempts", 0)) + 1
        max_retries = int(state.get("max_retries", _DEFAULT_MAX_RETRIES))

        # Exponential backoff
        delay = _BASE_DELAY_SECONDS * (_BACKOFF_MULTIPLIER ** (attempts - 1))
        delay = min(delay, _MAX_DELAY_SECONDS)

        # Add jitter to prevent thundering herd
        import hashlib
        jitter_seed = hashlib.md5(
            f"{state.get('task_id', '')}{attempts}".encode()
        ).hexdigest()
        jitter_offset = (int(jitter_seed[:8], 16) % 1000) / 1000.0
        jitter = delay * _JITTER_FACTOR * (jitter_offset - 0.5) * 2
        delay = max(0.1, delay + jitter)

        state["attempts"] = attempts
        state["last_error"] = str(error_message)
        state["next_delay_seconds"] = round(delay, 3)
        state["exhausted"] = attempts >= max_retries

        return state
    except Exception:
        return {
            "task_id": retry_state.get("task_id", "unknown"),
            "attempts": int(retry_state.get("attempts", 0)) + 1,
            "max_retries": int(retry_state.get("max_retries", _DEFAULT_MAX_RETRIES)),
            "last_error": str(error_message),
            "next_delay_seconds": _BASE_DELAY_SECONDS,
            "exhausted": True,
        }


def wait_for_retry(retry_state: dict[str, Any]) -> None:
    """Block for the computed backoff delay before retrying.

    Args:
        retry_state: Current retry state with next_delay_seconds.
    """
    delay = float(retry_state.get("next_delay_seconds", _BASE_DELAY_SECONDS))
    delay = min(delay, _MAX_DELAY_SECONDS)
    delay = max(0.0, delay)
    if delay > 0:
        time.sleep(delay)


def get_retry_summary(retry_states: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a summary of all retry activity.

    Args:
        retry_states: List of retry state dicts for all tasks that were retried.

    Returns:
        Summary dict with aggregate retry stats.
    """
    try:
        if not retry_states:
            return {
                "total_retried": 0,
                "total_attempts": 0,
                "exhausted_count": 0,
                "tasks": [],
            }

        total_attempts = sum(int(s.get("attempts", 0)) for s in retry_states)
        exhausted_count = sum(1 for s in retry_states if s.get("exhausted", False))

        task_summaries: list[dict[str, Any]] = []
        for state in retry_states:
            task_summaries.append({
                "task_id": state.get("task_id", "unknown"),
                "attempts": int(state.get("attempts", 0)),
                "max_retries": int(state.get("max_retries", _DEFAULT_MAX_RETRIES)),
                "exhausted": state.get("exhausted", False),
                "last_error": state.get("last_error", ""),
            })

        return {
            "total_retried": len(retry_states),
            "total_attempts": total_attempts,
            "exhausted_count": exhausted_count,
            "tasks": task_summaries,
        }
    except Exception:
        return {
            "total_retried": 0,
            "total_attempts": 0,
            "exhausted_count": 0,
            "tasks": [],
        }
