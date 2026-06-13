"""Backup/Recovery Engine — recovery tester.

Performs a dry-run recovery: reads a backup file, deserializes it,
validates schema compatibility, and checks that all expected sources
are present and parseable.
"""
from __future__ import annotations

import gzip
import json
import os
import time
from typing import Any


_SUPPORTED_SCHEMA_VERSIONS = {"1.0"}

# Rough estimate: seconds per 1000 records for restore operations
_SECONDS_PER_1000_RECORDS = 0.5


def test_recovery(
    path: str,
    sources: list[str],
) -> dict[str, Any]:
    """Perform a dry-run recovery test on a backup file.

    Args:
        path: Absolute path to the backup file.
        sources: List of source names expected in the backup.

    Returns:
        Structured dict with dry-run results.
    """
    try:
        if not os.path.isfile(path):
            return {
                "status": "error",
                "dry_run_success": False,
                "records_restorable": 0,
                "estimated_restore_seconds": 0.0,
                "error": f"Backup file not found: {path}",
            }

        # Read and decompress
        start = time.monotonic()
        raw_bytes = _read_file(path)
        json_bytes = _decompress_if_needed(raw_bytes)

        # Parse JSON
        try:
            envelope = json.loads(json_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return {
                "status": "error",
                "dry_run_success": False,
                "records_restorable": 0,
                "estimated_restore_seconds": 0.0,
                "error": f"Failed to parse backup data: {exc}",
            }

        # W962-75: json.loads can return any JSON type; defend
        # against list / scalar / None before .get on envelope.
        if not isinstance(envelope, dict):
            return {
                "status": "error",
                "dry_run_success": False,
                "records_restorable": 0,
                "estimated_restore_seconds": 0.0,
                "error": (
                    "Backup envelope is not an object "
                    f"(got {type(envelope).__name__})"
                ),
            }

        # Validate schema version
        schema_version = envelope.get("schema_version", "unknown")
        if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            return {
                "status": "error",
                "dry_run_success": False,
                "records_restorable": 0,
                "estimated_restore_seconds": 0.0,
                "error": f"Unsupported schema version: {schema_version}",
            }

        # Check all expected sources are present
        backup_sources = envelope.get("sources", {})
        missing_sources: list[str] = []
        records_restorable = 0

        for source in sources:
            if source not in backup_sources:
                missing_sources.append(source)
            else:
                source_data = backup_sources[source]
                records = source_data.get("records", [])
                # Validate each record is a dict (parseable)
                valid_records = sum(1 for r in records if isinstance(r, dict))
                records_restorable += valid_records

        if missing_sources:
            return {
                "status": "error",
                "dry_run_success": False,
                "records_restorable": records_restorable,
                "estimated_restore_seconds": 0.0,
                "error": f"Missing sources in backup: {missing_sources}",
            }

        # Estimate restore time based on record count and measured read time
        read_time = time.monotonic() - start
        estimated_restore = read_time + (
            records_restorable / 1000.0 * _SECONDS_PER_1000_RECORDS
        )

        return {
            "status": "success",
            "dry_run_success": True,
            "records_restorable": records_restorable,
            "estimated_restore_seconds": round(estimated_restore, 3),
        }
    except Exception as exc:
        return {
            "status": "error",
            "dry_run_success": False,
            "records_restorable": 0,
            "estimated_restore_seconds": 0.0,
            "error": f"Recovery test failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_file(path: str) -> bytes:
    """Read raw bytes from a file."""
    with open(path, "rb") as fh:
        return fh.read()


def _decompress_if_needed(data: bytes) -> bytes:
    """Decompress gzip data if magic bytes are present."""
    if len(data) >= 2 and data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    return data
