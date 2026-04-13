"""Autonomous Execution Engine — error handler.

Handle execution errors with retry logic and error classification.
"""
from __future__ import annotations

import copy
from typing import Any


def handle_errors(
    **kwargs: Any,
) -> dict[str, Any]:
    """Handle errors from dispatched actions.

    Args:
        **kwargs: Must include dispatch and progress data.

    Returns:
        Structured dict with error handling results.
    """
    try:
        dispatch_data = kwargs.get("action_dispatcher_data", {})
        dispatched = copy.deepcopy(dispatch_data.get("dispatched", []))
        config = kwargs.get("execution_config", {})
        max_retries = int(config.get("max_retries", 3))

        errors: list[dict[str, Any]] = []
        retryable: list[dict[str, Any]] = []

        for d in dispatched:
            if d.get("status") == "skipped" or d.get("error"):
                error_msg = d.get("error", "Unknown error")
                is_retryable = "timeout" in str(error_msg).lower() or "rate" in str(error_msg).lower()

                entry = {
                    "action": d.get("action", {}),
                    "error": error_msg,
                    "retryable": is_retryable,
                    "retry_count": 0,
                    "max_retries": max_retries,
                }
                errors.append(entry)
                if is_retryable:
                    retryable.append(entry)

        return {
            "status": "success",
            "result": {
                "errors": errors,
                "retryable": retryable,
                "total_errors": len(errors),
                "retryable_count": len(retryable),
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Error handling failed: {exc}"}
