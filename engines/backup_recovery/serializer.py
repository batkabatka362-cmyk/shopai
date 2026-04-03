"""Backup/Recovery Engine — serializer.

Serializes collected backup data to JSON with schema versioning,
computes SHA-256 checksums, and optionally compresses with gzip.
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import time
from typing import Any


_SCHEMA_VERSION = "1.0"


def serialize_data(
    collected: dict[str, Any],
    compress: bool = True,
) -> dict[str, Any]:
    """Serialize collected data to JSON with checksum and optional compression.

    Args:
        collected: Dict of source -> {records, count, size_bytes} from data_collector.
        compress: Whether to gzip-compress the serialized data.

    Returns:
        Structured dict with serialized bytes, checksum, and size info.
    """
    try:
        collected = copy.deepcopy(collected)

        if not collected:
            return {
                "status": "error",
                "serialized": b"",
                "checksum_sha256": "",
                "size_bytes": 0,
                "compressed_size_bytes": 0,
                "schema_version": _SCHEMA_VERSION,
                "error": "No data to serialize",
            }

        # Build the backup envelope
        envelope: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sources": {},
        }

        for source_name, source_data in collected.items():
            envelope["sources"][source_name] = {
                "records": source_data.get("records", []),
                "count": source_data.get("count", 0),
                "size_bytes": source_data.get("size_bytes", 0),
            }

        # Serialize to JSON bytes
        json_str = json.dumps(envelope, indent=2, default=str, sort_keys=True)
        json_bytes = json_str.encode("utf-8")
        raw_size = len(json_bytes)

        # Compute SHA-256 checksum on the raw JSON bytes
        checksum = hashlib.sha256(json_bytes).hexdigest()

        # Optionally compress
        if compress:
            compressed = gzip.compress(json_bytes, compresslevel=6)
            output_data = compressed
            compressed_size = len(compressed)
        else:
            output_data = json_bytes
            compressed_size = raw_size

        return {
            "status": "success",
            "serialized": output_data,
            "checksum_sha256": checksum,
            "size_bytes": raw_size,
            "compressed_size_bytes": compressed_size,
            "schema_version": _SCHEMA_VERSION,
        }
    except Exception as exc:
        return {
            "status": "error",
            "serialized": b"",
            "checksum_sha256": "",
            "size_bytes": 0,
            "compressed_size_bytes": 0,
            "schema_version": _SCHEMA_VERSION,
            "error": f"Serialization failed: {exc}",
        }
