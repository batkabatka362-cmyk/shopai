"""Backup/Recovery Engine — recovery tester.

Performs a dry-run recovery: reads a backup, deserializes it,
validates schema compatibility, and checks all sources are present and parseable.
"""
from __future__ import annotations

import gzip
import json
import time
from typing import Any

_SUPPORTED_SCHEMA_VERSIONS = {"1.0"}

# Estimated seconds per record for restore operations
_SECONDS_PER_RECORD = 0.002


def test_recovery(
    path: str,
    sources: list[str],
) -> dict[str, Any]:
    """Perform a dry-run recovery test.

    Reads the backup file, deserializes, validates schema compatibility,
    and checks that all requested sources are present and parseable.

    Args:
        path: Path to the backup file (.json or .json.gz).
        sources: List of source names that should be present.

    Returns:
        Structured dict with recovery test results.
    """
    try:
        if not path:
            return {
                "status": "error",
                "dry_run_success": False,
                "records_restorable": 0,
                "estimated_restore_seconds": 0.0,
                "error": "Path is required",
            }

        # ---- Step 1: Read and decompress ----
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
                "dry_run_success": False,
                "records_restorable": 0,
                "estimated_restore_seconds": 0.0,
                "error": f"Backup file not found: {path}",
            }

        # ---- Step 2: Deserialize ----
        try:
            payload = json.loads(json_bytes)
        except json.JSONDecodeError as je:
            return {
                "status": "error",
                "dry_run_success": False,
                "records_restorable": 0,
                "estimated_restore_seconds": 0.0,
                "error": f"JSON parse error: {je}",
            }

        if not isinstance(payload, dict):
            return {
                "status": "error",
                "dry_run_success": False,
                "records_restorable": 0,
                "estimated_restore_seconds": 0.0,
                "error": "Backup payload is not a dict",
            }

        # ---- Step 3: Validate schema version ----
        schema_version = payload.get("schema_version", "unknown")
        if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            return {
                "status": "error",
                "dry_run_success": False,
                "records_restorable": 0,
                "estimated_restore_seconds": 0.0,
                "error": f"Unsupported schema version: {schema_version}",
            }

        # ---- Step 4: Check all sources are present and parseable ----
        backup_sources = payload.get("sources", {})
        missing_sources: list[str] = []
        records_restorable = 0

        for source in sources:
            if source not in backup_sources:
                missing_sources.append(source)
                continue
            source_data = backup_sources[source]
            if not isinstance(source_data, dict):
                missing_sources.append(source)
                continue
            records = source_data.get("records", [])
            if not isinstance(records, list):
                missing_sources.append(source)
                continue
            records_restorable += len(records)

        if missing_sources:
            return {
                "status": "error",
                "dry_run_success": False,
                "records_restorable": records_restorable,
                "estimated_restore_seconds": 0.0,
                "error": f"Missing sources in backup: {missing_sources}",
            }

        # ---- Step 5: Estimate restore time ----
        estimated_seconds = round(records_restorable * _SECONDS_PER_RECORD, 3)

        return {
            "status": "success",
            "dry_run_success": True,
            "records_restorable": records_restorable,
            "estimated_restore_seconds": estimated_seconds,
        }
    except Exception as exc:
        return {
            "status": "error",
            "dry_run_success": False,
            "records_restorable": 0,
            "estimated_restore_seconds": 0.0,
            "error": f"Recovery test failed: {exc}",
        }
