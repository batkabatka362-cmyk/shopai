"""Backup/Recovery Engine — memory writer.

Persists backup metadata to disk for future reference.
Each backup run is stored as a separate JSON file keyed by record_id.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_backup_metadata(
    backup_id: str,
    manifest: dict[str, Any],
    integrity: dict[str, Any],
    recovery: dict[str, Any],
    checksum: str,
    storage_path: str,
    total_records: int,
    raw_size_bytes: int,
    final_size_bytes: int,
    compressed: bool,
    sources: list[str],
) -> dict[str, Any]:
    """Write backup metadata record to memory.

    Args:
        backup_id: Unique backup identifier.
        manifest: Dict of source -> {count, size_bytes} collected.
        integrity: Integrity verification result dict.
        recovery: Recovery test result dict.
        checksum: SHA-256 checksum of the backup data.
        storage_path: Where the backup was written.
        total_records: Total number of records backed up.
        raw_size_bytes: Size of uncompressed data.
        final_size_bytes: Size of the written file (may be compressed).
        compressed: Whether the backup was compressed.
        sources: List of source names backed up.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "backup_id": backup_id,
            "timestamp": timestamp,
            "sources": copy.deepcopy(sources),
            "total_records": total_records,
            "raw_size_bytes": raw_size_bytes,
            "final_size_bytes": final_size_bytes,
            "compressed": compressed,
            "checksum_sha256": checksum,
            "storage_path": storage_path,
            "manifest": copy.deepcopy(manifest),
            "integrity": {
                "verified": integrity.get("verified", False),
                "checksum_match": integrity.get("checksum_match", False),
                "records_verified": integrity.get("records_verified", 0),
                "errors": integrity.get("errors", []),
            },
            "recovery": {
                "dry_run_success": recovery.get("dry_run_success", False),
                "records_restorable": recovery.get("records_restorable", 0),
                "estimated_restore_seconds": recovery.get(
                    "estimated_restore_seconds", 0.0
                ),
            },
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
