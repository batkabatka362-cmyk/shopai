"""Legal Document Engine — memory writer.

Persists legal document generation results to disk for future reference.
Each run is stored as a separate JSON file keyed by record_id.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_document_result(
    documents: list[dict[str, Any]],
    compliance_check: dict[str, Any],
    missing_sections: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write a legal document result record to memory.

    Args:
        documents: List of generated document dicts.
        compliance_check: Compliance check result dict.
        missing_sections: List of missing section dicts.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "documents": copy.deepcopy(documents),
            "documents_count": len(documents),
            "compliance_check": copy.deepcopy(compliance_check),
            "missing_sections": copy.deepcopy(missing_sections),
            "outcome_actual": None,
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
