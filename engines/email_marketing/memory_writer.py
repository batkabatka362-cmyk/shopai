"""Email Marketing Engine — memory writer.

Persists completed campaign data to an in-process memory store so the
memory reader can surface past campaign performance for future runs.

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
    """Persist a campaign output to memory.

    Never mutates *output* — works on a deep copy.
    Returns the memory record that was stored, or ``None`` if the
    output was not suitable for storage (e.g. failed campaign).
    """
    safe = copy.deepcopy(output)

    if safe.get("status") != "success":
        return None

    data = safe.get("data")
    meta = safe.get("meta")

    if not isinstance(data, dict) or not isinstance(meta, dict):
        return None

    campaign = data.get("campaign", {})
    confidence = data.get("confidence", 0.0)
    timestamp = meta.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    record_id = _generate_id(
        campaign.get("send_time", ""),
        timestamp,
    )

    record: dict[str, Any] = {
        "record_id": record_id,
        "subject_lines": campaign.get("subject_lines", []),
        "audience_size": campaign.get("audience_size", 0),
        "send_time": campaign.get("send_time", ""),
        "predicted_performance": campaign.get("predicted_performance", {}),
        "confidence": confidence,
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

def _generate_id(send_time: str, timestamp: str) -> str:
    """Deterministic record ID from send_time + timestamp."""
    raw = f"email_campaign|{send_time}|{timestamp}".encode()
    return hashlib.sha256(raw).hexdigest()[:20]
