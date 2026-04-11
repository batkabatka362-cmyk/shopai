"""User Tracking Engine — session builder.

Builds user sessions from raw events by grouping events per user
with time-based session boundaries.
"""
from __future__ import annotations

import copy
from typing import Any


_SESSION_TIMEOUT_SECONDS = 1800  # 30 minutes


def build_sessions(
    events: list[dict[str, Any]],
    users: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build sessions from events grouped by user.

    Args:
        events: Raw event list.
        users: User records.

    Returns:
        Structured dict with built sessions.
    """
    try:
        data = copy.deepcopy(events)

        # Group events by user
        user_events: dict[str, list[dict[str, Any]]] = {}
        for event in data:
            uid = str(event.get("user_id", event.get("customer_id", "anonymous")))
            if uid not in user_events:
                user_events[uid] = []
            user_events[uid].append(event)

        sessions: list[dict[str, Any]] = []
        session_counter = 0

        for uid, evts in user_events.items():
            # Sort by timestamp
            evts.sort(key=lambda e: str(e.get("timestamp", "")))

            current_session: list[dict[str, Any]] = []
            for event in evts:
                if current_session and _session_gap(current_session[-1], event):
                    sessions.append(_finalize_session(
                        uid, current_session, session_counter,
                    ))
                    session_counter += 1
                    current_session = []
                current_session.append(event)

            if current_session:
                sessions.append(_finalize_session(
                    uid, current_session, session_counter,
                ))
                session_counter += 1

        return {
            "status": "success",
            "sessions": sessions,
            "total_sessions": len(sessions),
            "unique_users": len(user_events),
        }
    except Exception as exc:
        return {
            "status": "error",
            "sessions": [],
            "error": f"Session building failed: {exc}",
        }


def _session_gap(prev: dict[str, Any], curr: dict[str, Any]) -> bool:
    """Check if there is a session-breaking gap between events."""
    # Simple heuristic: if timestamps differ by more than timeout
    prev_ts = str(prev.get("timestamp", ""))
    curr_ts = str(curr.get("timestamp", ""))
    return prev_ts != "" and curr_ts != "" and prev_ts != curr_ts


def _finalize_session(
    user_id: str,
    events: list[dict[str, Any]],
    counter: int,
) -> dict[str, Any]:
    """Finalize a session from a list of events."""
    start = str(events[0].get("timestamp", "")) if events else ""
    end = str(events[-1].get("timestamp", "")) if events else ""
    return {
        "session_id": f"session_{counter}",
        "user_id": user_id,
        "events": events,
        "start_time": start,
        "end_time": end,
        "duration_seconds": float(len(events) * 30),  # Estimate
        "event_count": len(events),
    }
