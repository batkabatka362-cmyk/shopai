"""Memory Writer — persists research results to a memory store.

Responsibility: take a completed ``ResearchOutput`` and write it as a
``MemoryRecord`` to the in-process memory store.  This enables the
Memory Reader to surface past research for deduplication and context.

The store is a simple module-level list (in production, a database or
key-value store).  Thread-safety is out of scope for this placeholder.

Model note: no model usage — pure persistence.
"""
from __future__ import annotations

import copy
import hashlib
import time
from typing import Any

from .types import MemoryRecord


# ---------------------------------------------------------------------------
# In-process memory store (module-level singleton)
# ---------------------------------------------------------------------------

_STORE: list[MemoryRecord] = []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_to_memory(output: dict[str, Any]) -> MemoryRecord | None:
    """Persist a research output to memory.

    Never mutates *output* — works on a deep copy.
    Returns the ``MemoryRecord`` that was stored, or ``None`` if the
    output was not suitable for storage (e.g. failed research).
    """
    safe_output: dict[str, Any] = copy.deepcopy(output)

    if safe_output.get("status") != "success":
        return None

    data = safe_output.get("data")
    meta = safe_output.get("meta")

    if not isinstance(data, dict) or not isinstance(meta, dict):
        return None

    query = meta.get("query", "")
    insight = data.get("insight", "")
    key_findings = data.get("key_findings", [])
    confidence = data.get("confidence", 0.0)
    sources = meta.get("sources", [])
    timestamp = meta.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    record_id = _generate_id(query, timestamp)

    record = MemoryRecord(
        record_id=record_id,
        query=query,
        insight=insight,
        key_findings=key_findings,
        confidence=confidence,
        sources=sources,
        timestamp=timestamp,
    )

    _STORE.append(record)
    return record


def get_store() -> list[MemoryRecord]:
    """Return a shallow copy of the current memory store.

    Callers should not mutate the returned list.
    """
    return list(_STORE)


def clear_store() -> int:
    """Clear all records from the memory store.

    Returns the number of records that were removed.
    """
    count = len(_STORE)
    _STORE.clear()
    return count


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_id(query: str, timestamp: str) -> str:
    """Deterministic record ID from query + timestamp."""
    raw = f"{query}|{timestamp}".encode()
    return hashlib.sha256(raw).hexdigest()[:20]
