"""Webhook Handler Engine — execution tracker.

Creates dispatch records for each routed engine and tracks their
initial dispatch status. Actual engine execution is asynchronous;
this module records the intent to dispatch.
"""
from __future__ import annotations

import time
import uuid
from typing import Any


def track_execution(
    routes: list[dict[str, Any]],
    webhook_id: str,
) -> dict[str, Any]:
    """Create dispatch records for each routed engine.

    Generates a dispatch record per route entry, stamped with the
    webhook_id, a unique dispatch_id, and an initial status of
    "dispatched".

    Args:
        routes: List of route dicts from engine_router.
        webhook_id: The unique webhook identifier.

    Returns:
        Structured dict with dispatch records and count.
    """
    try:
        if not isinstance(routes, list):
            return {
                "status": "error",
                "dispatched_count": 0,
                "dispatch_status": [],
                "error": "routes must be a list",
            }

        if not webhook_id:
            return {
                "status": "error",
                "dispatched_count": 0,
                "dispatch_status": [],
                "error": "webhook_id is required",
            }

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        dispatch_records: list[dict[str, Any]] = []

        for route in routes:
            engine_name = route.get("engine", "unknown")
            action = route.get("action", "unknown")
            priority = route.get("priority", "medium")

            dispatch_id = uuid.uuid4().hex[:12]

            record: dict[str, Any] = {
                "dispatch_id": dispatch_id,
                "engine": engine_name,
                "action": action,
                "priority": priority,
                "webhook_id": webhook_id,
                "dispatch_status": "dispatched",
                "dispatched_at": timestamp,
            }

            dispatch_records.append(record)

        return {
            "status": "success",
            "dispatched_count": len(dispatch_records),
            "dispatch_status": dispatch_records,
        }
    except Exception as exc:
        return {
            "status": "error",
            "dispatched_count": 0,
            "dispatch_status": [],
            "error": f"Execution tracking failed: {exc}",
        }
