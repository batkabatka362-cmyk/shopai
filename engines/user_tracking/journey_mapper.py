"""User Tracking Engine — journey mapper.

Maps customer journeys from sessions: ordered sequence of
touchpoints from first contact to conversion or exit.
"""
from __future__ import annotations

import copy
from typing import Any


def map_journeys(
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Map customer journeys from built sessions.

    Args:
        sessions: Built user sessions.

    Returns:
        Structured dict with mapped journeys.
    """
    try:
        data = copy.deepcopy(sessions)

        # Group sessions by user
        user_sessions: dict[str, list[dict[str, Any]]] = {}
        for session in data:
            uid = session.get("user_id", "anonymous")
            if uid not in user_sessions:
                user_sessions[uid] = []
            user_sessions[uid].append(session)

        journeys: list[dict[str, Any]] = []

        for uid, user_sess in user_sessions.items():
            user_sess.sort(key=lambda s: s.get("start_time", ""))

            steps: list[dict[str, Any]] = []
            step_num = 1
            converted = False

            for session in user_sess:
                events = session.get("events", [])
                for event in events:
                    etype = str(event.get("type", "unknown"))
                    channel = str(event.get("channel", event.get("source", "direct")))

                    steps.append({
                        "step_number": step_num,
                        "touchpoint": etype,
                        "channel": channel,
                        "timestamp": str(event.get("timestamp", "")),
                    })
                    step_num += 1

                    if etype in ("purchase", "checkout_complete", "conversion"):
                        converted = True

            journeys.append({
                "user_id": uid,
                "steps": steps,
                "total_steps": len(steps),
                "converted": converted,
                "sessions_count": len(user_sess),
            })

        converted_count = sum(1 for j in journeys if j["converted"])
        conversion_rate = (
            round(converted_count / len(journeys) * 100, 1) if journeys else 0.0
        )

        return {
            "status": "success",
            "journeys": journeys,
            "total_journeys": len(journeys),
            "conversion_rate_pct": conversion_rate,
        }
    except Exception as exc:
        return {
            "status": "error",
            "journeys": [],
            "error": f"Journey mapping failed: {exc}",
        }
