"""Social Media Engine — memory writer.

Persists completed social media pipeline output to an in-process memory
store so the memory reader can surface past performance for future runs.

Model note: no model usage — pure persistence.
"""
from __future__ import annotations

import copy
import hashlib
import time
from typing import Any


# ---------------------------------------------------------------------------
# In-process memory store (module-level singleton)
# ---------------------------------------------------------------------------

_STORE: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_to_memory(output: dict[str, Any]) -> dict[str, Any] | None:
    """Persist a social media pipeline output to memory.

    Never mutates *output* — works on a deep copy.
    Returns the memory record that was stored, or ``None`` if the
    output was not suitable for storage (e.g. failed run).
    """
    safe = copy.deepcopy(output)

    if safe.get("status") != "success":
        return None

    data = safe.get("data")
    meta = safe.get("meta")

    if not isinstance(data, dict) or not isinstance(meta, dict):
        return None

    timestamp = meta.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    record_id = _generate_id(timestamp)

    record: dict[str, Any] = {
        "record_id": record_id,
        "platforms": [p.get("platform", "") for p in data.get("posts", [])],
        "post_count": len(data.get("posts", [])),
        "schedule_slots": len(data.get("schedule", {}).get("slots", [])),
        "engagement_rate": data.get("predicted_engagement", {}).get("overall_engagement_rate", 0.0),
        "confidence": data.get("confidence", 0.0),
        "best_performing_type": data.get("predicted_engagement", {}).get("best_performing_type", ""),
        "trending_count": len(data.get("trending", [])),
        "timestamp": timestamp,
    }

    _STORE.append(record)
    return record


def get_store() -> list[dict[str, Any]]:
    """Return a shallow copy of the current memory store."""
    return list(_STORE)


def clear_store() -> int:
    """Clear all records.  Returns the count of removed records."""
    count = len(_STORE)
    _STORE.clear()
    return count


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_id(timestamp: str) -> str:
    """Deterministic record ID from engine name + timestamp."""
    raw = f"social_media|{timestamp}".encode()
    return hashlib.sha256(raw).hexdigest()[:20]
