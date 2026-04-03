"""Event Tracking Engine — event collector.

Collects and groups events by type, validates event structure,
and produces grouped event summaries.
"""
from __future__ import annotations

import copy
from typing import Any


def collect_events(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Collect and group events by type.

    Args:
        events: List of raw event dicts.

    Returns:
        Structured dict with grouped events.
    """
    try:
        data = copy.deepcopy(events)
        groups: dict[str, list[dict[str, Any]]] = {}
        invalid_count = 0

        for event in data:
            if not isinstance(event, dict):
                invalid_count += 1
                continue

            event_type = str(event.get("type", "unknown"))

            if event_type not in groups:
                groups[event_type] = []
            groups[event_type].append(event)

        result_groups: list[dict[str, Any]] = []
        for etype, evts in sorted(groups.items()):
            result_groups.append({
                "event_type": etype,
                "events": evts,
                "count": len(evts),
            })

        return {
            "status": "success",
            "groups": result_groups,
            "total_events": sum(g["count"] for g in result_groups),
            "unique_types": len(result_groups),
            "invalid_count": invalid_count,
        }
    except Exception as exc:
        return {
            "status": "error",
            "groups": [],
            "error": f"Event collection failed: {exc}",
        }
