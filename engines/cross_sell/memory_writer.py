"""Cross-Sell Engine — memory writer.

Persists completed cross-sell engine output to an in-process memory store
so the memory reader can surface past cross-sell performance for future runs.

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
    """Persist a cross-sell engine output to memory.

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

    timestamp = meta.get(
        "timestamp",
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    recommendations = data.get("recommendations", [])
    bundles = data.get("bundles", [])

    record_id = _generate_id(
        [r.get("product_id", "") for r in recommendations[:5]],
        timestamp,
    )

    record: dict[str, Any] = {
        "record_id": record_id,
        "recommendation_count": len(recommendations),
        "bundle_count": len(bundles),
        "top_product_ids": [r.get("product_id", "") for r in recommendations[:5]],
        "top_scores": [r.get("score", 0) for r in recommendations[:5]],
        "estimated_aov_increase": data.get("estimated_aov_increase", 0.0),
        "confidence": data.get("confidence", 0.0),
        "elapsed_seconds": meta.get("elapsed_seconds", 0.0),
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

def _generate_id(product_ids: list[str], timestamp: str) -> str:
    """Deterministic record ID from product IDs + timestamp."""
    raw = f"cross_sell|{'|'.join(product_ids)}|{timestamp}".encode()
    return hashlib.sha256(raw).hexdigest()[:20]
