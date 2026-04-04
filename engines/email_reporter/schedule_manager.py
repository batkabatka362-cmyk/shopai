"""Email Reporter Engine — schedule manager.

Manages report delivery schedules.
"""
from __future__ import annotations

import time
from typing import Any

_SCHEDULE_MAP = {
    "daily": {"frequency": "daily", "hour": 8, "interval_days": 1},
    "weekly": {"frequency": "weekly", "hour": 9, "interval_days": 7},
    "monthly": {"frequency": "monthly", "hour": 9, "interval_days": 30},
}


def manage_schedule(
    report_type: str,
) -> dict[str, Any]:
    """Determine schedule for the report type."""
    try:
        config = _SCHEDULE_MAP.get(report_type, _SCHEDULE_MAP["weekly"])

        # Calculate next send time
        now = time.time()
        interval_seconds = config["interval_days"] * 86400
        next_send_ts = now + interval_seconds
        next_send = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(next_send_ts))

        schedule = {
            "frequency": config["frequency"],
            "next_send": next_send,
            "timezone": "UTC",
            "send_hour": config["hour"],
        }

        return {"status": "success", "schedule": schedule}
    except Exception as exc:
        return {"status": "error", "schedule": {}, "error": f"Schedule management failed: {exc}"}
