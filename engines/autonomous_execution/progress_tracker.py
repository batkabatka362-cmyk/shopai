"""Autonomous Execution Engine — progress tracker.

Track execution progress across all dispatched actions.
"""
from __future__ import annotations

import copy
from typing import Any


def track_progress(
    **kwargs: Any,
) -> dict[str, Any]:
    """Track execution progress.

    Args:
        **kwargs: Must include action_dispatcher_data with dispatch results.

    Returns:
        Structured dict with progress tracking data.
    """
    try:
        dispatch_data = kwargs.get("action_dispatcher_data", {})
        dispatched = copy.deepcopy(dispatch_data.get("dispatched", []))
        total = len(dispatched)

        completed = sum(1 for d in dispatched if d.get("status") in ("dispatched", "dry_run"))
        skipped = sum(1 for d in dispatched if d.get("status") == "skipped")
        failed = sum(1 for d in dispatched if d.get("status") == "failed")

        pct = round(completed / max(total, 1) * 100, 1)

        return {
            "status": "success",
            "result": {
                "total": total,
                "completed": completed,
                "skipped": skipped,
                "failed": failed,
                "progress_pct": pct,
                "phase": "complete" if pct >= 100 else "in_progress",
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Progress tracking failed: {exc}"}
