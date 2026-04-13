"""Cart Recovery Engine — memory writer.

Persists completed recovery attempt data to an in-process memory store
so the memory reader can surface past recovery performance for future runs.

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
    """Persist a recovery attempt output to memory.

    Never mutates *output* — works on a deep copy.
    Returns the memory record that was stored, or ``None`` if the
    output was not suitable for storage (e.g. failed recovery).
    """
    safe = copy.deepcopy(output)

    if safe.get("status") != "success":
        return None

    data = safe.get("data")
    meta = safe.get("meta")

    if not isinstance(data, dict) or not isinstance(meta, dict):
        return None

    timestamp = meta.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    pipeline_stats = meta.get("pipeline_stats", {})

    record_id = _generate_id(
        data.get("strategy", ""),
        data.get("channel", ""),
        timestamp,
    )

    record: dict[str, Any] = {
        "record_id": record_id,
        "strategy": data.get("strategy", ""),
        "channel": data.get("channel", ""),
        "incentive_type": data.get("incentive", {}).get("type", "none"),
        "incentive_value": data.get("incentive", {}).get("value", 0),
        "recovery_probability": data.get("recovery_probability", 0.0),
        "expected_revenue": data.get("expected_revenue", 0.0),
        "confidence": data.get("confidence", 0.0),
        "customer_type": pipeline_stats.get("customer_type", "unknown"),
        "abandonment_reason": pipeline_stats.get("abandonment_reason", "unknown"),
        "cart_value": pipeline_stats.get("cart_value", 0.0),
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

def _generate_id(strategy: str, channel: str, timestamp: str) -> str:
    """Deterministic record ID from strategy + channel + timestamp."""
    raw = f"cart_recovery|{strategy}|{channel}|{timestamp}".encode()
    return hashlib.sha256(raw).hexdigest()[:20]
