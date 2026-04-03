"""Backup/Recovery Engine — integrity verifier.

Re-reads backup files, recomputes SHA-256 checksums, and verifies
record counts match expectations.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from typing import Any


def verify_integrity(
    path: str,
    expected_checksum: str,
    expected_records: int,
) -> dict[str, Any]:
    """Verify integrity of a backup file.

    Re-reads the file, recomputes SHA-256 on the raw JSON, and compares
    with the expected checksum. Also counts records and compares.

    Args:
        path: Path to the backup file (.json or .json.gz).
        expected_checksum: Expected SHA-256 hex digest of the raw JSON.
        expected_records: Expected total record count.

    Returns:
        Structured dict with verification results.
    """
    try:
        errors: list[str] = []

        if not path:
            return {
                "status": "error",
                "verified": False,
                "checksum_match": False,
                "records_verified": 0,
                "errors": ["Path is required"],
                "error": "Path is required",
            }

        # Read the file — decompress if gzipped
        is_gzipped = path.endswith(".gz")
        try:
            if is_gzipped:
                with open(path, "rb") as fh:
                    compressed = fh.read()
                json_bytes = gzip.decompress(compressed)
            else:
                with open(path, "r", encoding="utf-8") as fh:
                    raw = fh.read()
                json_bytes = raw.encode("utf-8")
        except FileNotFoundError:
            return {
                "status": "error",
                "verified": False,
                "checksum_match": False,
                "records_verified": 0,
                "errors": [f"Backup file not found: {path}"],
                "error": f"Backup file not found: {path}",
            }
        except Exception as read_exc:
            return {
                "status": "error",
                "verified": False,
                "checksum_match": False,
                "records_verified": 0,
                "errors": [f"Failed to read backup: {read_exc}"],
                "error": f"Failed to read backup: {read_exc}",
            }

        # Recompute SHA-256 on the raw JSON bytes
        actual_checksum = hashlib.sha256(json_bytes).hexdigest()
        checksum_match = actual_checksum == expected_checksum

        if not checksum_match:
            errors.append(
                f"Checksum mismatch: expected {expected_checksum[:16]}..., "
                f"got {actual_checksum[:16]}..."
            )

        # Parse JSON and count records
        try:
            payload = json.loads(json_bytes)
        except json.JSONDecodeError as je:
            return {
                "status": "error",
                "verified": False,
                "checksum_match": checksum_match,
                "records_verified": 0,
                "errors": errors + [f"JSON parse error: {je}"],
                "error": f"JSON parse error: {je}",
            }

        records_verified = _count_records(payload)

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

def _count_records(payload: dict) -> int:
    """Count total records across all sources in the backup payload."""
    sources = payload.get("sources", {})
    total = 0
    for _source_name, source_data in sources.items():
        if isinstance(source_data, dict):
            records = source_data.get("records", [])
            if isinstance(records, list):
                total += len(records)
    return total
