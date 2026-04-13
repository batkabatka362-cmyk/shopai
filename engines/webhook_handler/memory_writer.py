"""Webhook Handler Engine — memory writer.

Persists webhook processing records to disk for deduplication
and audit trail. Each webhook is stored as a separate JSON file.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_webhook_record(
    webhook_id: str,
    topic: str,
    routes: list[dict[str, Any]],
    signature_valid: bool = True,
    entity_type: str = "",
    entity_id: str = "",
    dispatched_count: int = 0,
) -> dict[str, Any]:
    """Write a webhook processing record to memory.

    Args:
        webhook_id: The unique webhook identifier.
        topic: The Shopify webhook topic.
        routes: List of route decision dicts.
        signature_valid: Whether the HMAC signature was valid.
        entity_type: The parsed entity type (order, product, etc.).
        entity_id: The parsed entity ID.
        dispatched_count: Number of engines dispatched to.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "webhook_id": webhook_id,
            "topic": topic,
            "timestamp": timestamp,
            "signature_valid": signature_valid,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "dispatched_count": dispatched_count,
            "routes": copy.deepcopy(routes),
        }

        _ensure_memory_dir()
        fpath = os.path.join(_MEMORY_DIR, f"{record_id}.json")
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, default=str)

        return {
            "status": "success",
            "record_id": record_id,
            "path": fpath,
        }
    except Exception as exc:
        return {
            "status": "warning",
            "record_id": None,
            "path": None,
            "note": f"Memory write failed (non-fatal): {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
