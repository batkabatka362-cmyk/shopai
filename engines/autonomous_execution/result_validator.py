"""Autonomous Execution Engine — result validator.

Validate execution results for completeness and correctness.
"""
from __future__ import annotations

import copy
from typing import Any


def validate_results(
    **kwargs: Any,
) -> dict[str, Any]:
    """Validate execution results.

    Args:
        **kwargs: Must include all prior stage data.

    Returns:
        Structured dict with validation results and final executed/failed lists.
    """
    try:
        dispatch_data = kwargs.get("action_dispatcher_data", {})
        dispatched = copy.deepcopy(dispatch_data.get("dispatched", []))
        progress_data = kwargs.get("progress_tracker_data", {})
        error_data = kwargs.get("error_handler_data", {})

        error_actions = {str(e.get("action", {}).get("id", "")) for e in error_data.get("errors", [])}

        executed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []

        # Post-cleanup note: ``action_dispatcher`` no longer invents
        # a ``"dispatched"`` status for non-dry-run actions — it
        # returns ``"adapter_required"`` instead (see
        # ``action_dispatcher.py`` for the rationale). We still
        # count legacy ``"dispatched"`` as executed so older
        # pre-cleanup callers keep working, but the new state is
        # surfaced in its own ``pending`` bucket so callers can
        # see how many actions are waiting for the adapter layer.
        for d in dispatched:
            action = d.get("action", {})
            action_id = str(action.get("id", "unknown"))
            status = d.get("status")

            if status in ("dispatched", "dry_run") and action_id not in error_actions:
                executed.append({
                    "action": action,
                    "status": "success",
                    "result": d.get("result", {}),
                })
            elif status == "adapter_required":
                pending.append({
                    "action": action,
                    "status": "adapter_required",
                    "result": d.get("result", {}),
                })
            else:
                failed.append({
                    "action": action,
                    "error": d.get("error", "Validation failed"),
                })

        progress = {
            "total": len(dispatched),
            "executed": len(executed),
            "failed": len(failed),
            "pending": len(pending),
            "success_rate": round(len(executed) / max(len(dispatched), 1), 2),
            "phase": progress_data.get("phase", "complete"),
        }

        return {
            "status": "success",
            "result": {
                "executed": executed,
                "failed": failed,
                "pending": pending,
                "progress": progress,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Result validation failed: {exc}"}
