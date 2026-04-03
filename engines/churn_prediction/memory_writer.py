"""Churn Prediction Engine — memory writer.

Persists completed churn prediction data to an in-process memory store
so the memory reader can surface past predictions for accuracy tracking.

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
    """Persist a churn prediction output to memory.

    Never mutates *output* — works on a deep copy.
    Returns the memory record that was stored, or ``None`` if the
    output was not suitable for storage (e.g. failed prediction).
    """
    safe = copy.deepcopy(output)

    if safe.get("status") != "success":
        return None

    data = safe.get("data")
    meta = safe.get("meta")

    if not isinstance(data, dict) or not isinstance(meta, dict):
        return None

    timestamp = meta.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    predictions = data.get("predictions", [])
    summary = data.get("summary", {})

    record_id = _generate_id(timestamp, summary.get("total_analyzed", 0))

    record: dict[str, Any] = {
        "record_id": record_id,
        "total_analyzed": summary.get("total_analyzed", 0),
        "high_risk_count": summary.get("high_risk_count", 0),
        "avg_churn_probability": summary.get("avg_churn_probability", 0.0),
        "confidence": data.get("confidence", 0.0),
        "predictions": predictions,
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

def _generate_id(timestamp: str, total_analyzed: int) -> str:
    """Deterministic record ID from timestamp + batch size."""
    raw = f"churn_prediction|{timestamp}|{total_analyzed}".encode()
    return hashlib.sha256(raw).hexdigest()[:20]
