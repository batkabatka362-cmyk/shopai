"""Customer Service Engine — memory writer.

Persists customer interaction records to disk for future reference.
Each interaction is stored as a separate JSON file keyed by record_id.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_interaction_record(
    customer_id: str,
    message: str,
    intent: str,
    channel: str,
    response_message: str,
    escalated: bool,
    assigned_team: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Write a customer interaction record to memory.

    Args:
        customer_id: Customer identifier.
        message: The original customer message.
        intent: Classified primary intent.
        channel: Communication channel (chat, email, etc.).
        response_message: The generated response.
        escalated: Whether the interaction was escalated.
        assigned_team: Team assigned if escalated.
        session_id: Optional conversation session ID.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "customer_id": str(customer_id) if customer_id else "anonymous",
            "session_id": session_id,
            "channel": str(channel) if channel else "unknown",
            "message_preview": _truncate(message, 200),
            "intent": str(intent),
            "response_preview": _truncate(response_message, 200),
            "escalated": bool(escalated),
            "assigned_team": assigned_team,
            "resolution": "escalated" if escalated else "auto_resolved",
            "satisfaction_score": None,  # to be filled by follow-up survey
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

def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len characters."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
