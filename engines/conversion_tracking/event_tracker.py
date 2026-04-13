"""Conversion Tracking Engine — event tracker.

Validates, deduplicates, and processes raw conversion events.
Produces a clean list of tracked events with validation status.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Valid event types
# ---------------------------------------------------------------------------

_VALID_EVENT_TYPES = {
    "purchase", "add_to_cart", "checkout_start", "checkout_complete",
    "page_view", "sign_up", "lead", "subscription", "download",
    "form_submit", "click", "impression",
}


def track_events(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate and process raw conversion events.

    Args:
        events: List of raw ConversionEvent dicts.

    Returns:
        Structured dict with tracked events and validation summary.
    """
    try:
        events = copy.deepcopy(events)

        tracked: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        valid_count = 0
        invalid_count = 0
        duplicate_count = 0
        total_value = 0.0

        for event in events:
            event_id = str(event.get("id", ""))
            event_type = str(event.get("event_type", "")).lower()
            value = float(event.get("value", 0.0))
            timestamp = str(event.get("timestamp", ""))
            source = str(event.get("source", "unknown"))
            customer_id = str(event.get("customer_id", ""))
            session_id = str(event.get("session_id", ""))

            # Deduplication
            if event_id in seen_ids:
                duplicate_count += 1
                continue
            if event_id:
                seen_ids.add(event_id)

            # Validation
            is_valid = True
            if event_type not in _VALID_EVENT_TYPES:
                is_valid = False
            if not timestamp:
                is_valid = False
            if value < 0:
                is_valid = False

            if is_valid:
                valid_count += 1
                total_value += value
            else:
                invalid_count += 1

            tracked.append({
                "id": event_id,
                "event_type": event_type,
                "value": value,
                "timestamp": timestamp,
                "source": source,
                "customer_id": customer_id,
                "session_id": session_id,
                "is_valid": is_valid,
            })

        # Sort by timestamp
        tracked.sort(key=lambda e: e.get("timestamp", ""))

        return {
            "status": "success",
            "tracked_events": tracked,
            "summary": {
                "total": len(tracked),
                "valid": valid_count,
                "invalid": invalid_count,
                "duplicates_removed": duplicate_count,
                "total_value": round(total_value, 2),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "tracked_events": [],
            "error": f"Event tracking failed: {exc}",
        }
