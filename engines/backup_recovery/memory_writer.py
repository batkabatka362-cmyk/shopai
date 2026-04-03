"""Backup/Recovery Engine — memory writer.

Records backup metadata to .memory/backup_recovery/ for future reference.
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
    total_records: int,
    size_bytes: int,
    compressed_size_bytes: int,
    storage_path: str,
    checksum_sha256: str,
) -> dict[str, Any]:
    """Record backup metadata to memory.

    Args:
        backup_id: Unique backup identifier.
        manifest: Dict of source names to record counts.
        integrity: Integrity verification result summary.
        recovery: Recovery test result summary.
        total_records: Total records across all sources.
        size_bytes: Raw (uncompressed) size in bytes.
        compressed_size_bytes: Compressed size in bytes.
        storage_path: Where the backup was written.
        checksum_sha256: SHA-256 of the raw JSON data.

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
            "manifest": copy.deepcopy(manifest),
            "integrity": {
                "verified": integrity.get("verified", False),
                "checksum_match": integrity.get("checksum_match", False),
                "errors": integrity.get("errors", []),
            },
            "recovery": {
                "dry_run_success": recovery.get("dry_run_success", False),
                "records_restorable": recovery.get("records_restorable", 0),
                "estimated_restore_seconds": recovery.get("estimated_restore_seconds", 0.0),
            },
            "total_records": total_records,
            "size_bytes": size_bytes,
            "compressed_size_bytes": compressed_size_bytes,
            "storage_path": storage_path,
            "checksum_sha256": checksum_sha256,
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
