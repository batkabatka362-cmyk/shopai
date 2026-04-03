"""Backup/Recovery Engine — integrity verifier.

Re-reads a backup file from disk, recomputes its SHA-256 checksum,
and compares against the expected checksum and record count.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from typing import Any


def verify_integrity(
    path: str,
    expected_checksum: str,
    expected_records: int,
) -> dict[str, Any]:
    """Verify the integrity of a written backup file.

    Args:
        path: Absolute path to the backup file.
        expected_checksum: Expected SHA-256 hex digest of the raw JSON data.
        expected_records: Expected total number of records across all sources.

    Returns:
        Structured dict with verification results.
    """
    try:
        errors: list[str] = []

        if not os.path.isfile(path):
            return {
                "status": "error",
                "verified": False,
                "checksum_match": False,
                "records_verified": 0,
                "errors": [f"Backup file not found: {path}"],
                "error": f"Backup file not found: {path}",
            }

        # Read the file
        raw_bytes = _read_backup_bytes(path)

        # Decompress if gzipped
        json_bytes = _decompress_if_needed(raw_bytes)

        # Compute SHA-256 on raw JSON bytes
        actual_checksum = hashlib.sha256(json_bytes).hexdigest()
        checksum_match = actual_checksum == expected_checksum

        if not checksum_match:
            errors.append(
                f"Checksum mismatch: expected {expected_checksum[:16]}..., "
                f"got {actual_checksum[:16]}..."
            )

        # Parse and count records
        records_verified = _count_records(json_bytes)

        if records_verified != expected_records:
            errors.append(
                f"Record count mismatch: expected {expected_records}, "
                f"got {records_verified}"
            )

        verified = checksum_match and records_verified == expected_records

        return {
            "status": "success",
            "verified": verified,
            "checksum_match": checksum_match,
            "records_verified": records_verified,
            "errors": errors,
        }
    except Exception as exc:
        return {
            "status": "error",
            "verified": False,
            "checksum_match": False,
            "records_verified": 0,
            "errors": [str(exc)],
            "error": f"Integrity verification failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_backup_bytes(path: str) -> bytes:
    """Read the raw bytes of a backup file."""
    with open(path, "rb") as fh:
        return fh.read()


def _decompress_if_needed(data: bytes) -> bytes:
    """Decompress gzip data if the magic bytes are present."""
    if len(data) >= 2 and data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    return data


def _count_records(json_bytes: bytes) -> int:
    """Parse JSON envelope and count total records across all sources."""
    try:
        envelope = json.loads(json_bytes.decode("utf-8"))
        sources = envelope.get("sources", {})
        total = 0
        for source_data in sources.values():
            records = source_data.get("records", [])
            total += len(records)
        return total
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
