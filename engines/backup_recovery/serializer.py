"""Backup/Recovery Engine — serializer.

Serializes collected data to JSON, computes SHA-256 checksum,
and optionally compresses with gzip.
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
        compress: Whether to gzip-compress the output.

    Returns:
        Structured dict with serialized data, checksum, and size info.
    """
    try:
        collected = copy.deepcopy(collected)

        # Build the backup payload with schema metadata
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sources": collected,
        }

        # Serialize to JSON bytes
        json_str = json.dumps(payload, indent=2, default=str, sort_keys=True)
        json_bytes = json_str.encode("utf-8")
        raw_size = len(json_bytes)

        # Compute SHA-256 on the raw (uncompressed) JSON
        checksum = hashlib.sha256(json_bytes).hexdigest()

        # Optionally compress
        if compress:
            compressed_bytes = gzip.compress(json_bytes, compresslevel=6)
            compressed_size = len(compressed_bytes)
            serialized = compressed_bytes
        else:
            compressed_size = raw_size
            serialized = json_str

        return {
            "status": "success",
            "serialized": serialized,
            "checksum_sha256": checksum,
            "size_bytes": raw_size,
            "compressed_size_bytes": compressed_size,
            "schema_version": _SCHEMA_VERSION,
        }
    except Exception as exc:
        return {
            "status": "error",
            "serialized": None,
            "checksum_sha256": "",
            "size_bytes": 0,
            "compressed_size_bytes": 0,
            "schema_version": _SCHEMA_VERSION,
            "error": f"Serialization failed: {exc}",
        }
