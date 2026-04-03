"""Backup/Recovery Engine — data collector.

Collects data from .memory/ directories for each requested source.
Reads JSON files from engine memory directories (products, orders, customers, settings).
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

# Base path: project root .memory/ directories live alongside engines
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Map source names to their .memory/ directories
_SOURCE_DIRS: dict[str, str] = {
    "products": os.path.join(_PROJECT_ROOT, "engines", "inventory", ".memory"),
    "orders": os.path.join(_PROJECT_ROOT, "engines", "orders", ".memory"),
    "customers": os.path.join(_PROJECT_ROOT, "engines", "customers", ".memory"),
    "settings": os.path.join(_PROJECT_ROOT, "engines", "settings", ".memory"),
}


def collect_data(
    sources: list[str],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect data from .memory/ directories for each source.

    Args:
        sources: List of source names to collect (e.g. ["products", "orders"]).
        options: Optional dict with collection options.

    Returns:
        Structured dict with collected data per source.
    """
    try:
        sources = copy.deepcopy(sources)
        options = copy.deepcopy(options) if options else {}

        if not sources:
            return {
                "status": "error",
                "collected": {},
                "total_records": 0,
                "error": "No sources specified for collection",
            }

        collected: dict[str, dict[str, Any]] = {}
        total_records = 0

        for source in sources:
            source_dir = _SOURCE_DIRS.get(source)

            # Allow custom source directories via options
            if source_dir is None and "source_dirs" in options:
                source_dir = options["source_dirs"].get(source)

            if source_dir is None:
                # Unknown source — collect empty with a note
                collected[source] = {
                    "records": [],
                    "count": 0,
                    "size_bytes": 0,
                    "note": f"No known directory for source '{source}'",
                }
                continue

            records, size_bytes = _read_source_dir(source_dir)
            count = len(records)
            total_records += count

            collected[source] = {
                "records": records,
                "count": count,
                "size_bytes": size_bytes,
            }

        return {
            "status": "success",
            "collected": collected,
            "total_records": total_records,
        }
    except Exception as exc:
        return {
            "status": "error",
            "collected": {},
            "total_records": 0,
            "error": f"Data collection failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_source_dir(directory: str) -> tuple[list[dict[str, Any]], int]:
    """Read all JSON files from a directory.

    Returns:
        Tuple of (list of records, total size in bytes).
    """
    if not os.path.isdir(directory):
        return [], 0

    records: list[dict[str, Any]] = []
    total_size = 0

    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(directory, fname)
        try:
            file_size = os.path.getsize(fpath)
            total_size += file_size
            with open(fpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    records.append(data)
                elif isinstance(data, list):
                    records.extend(data)
        except (json.JSONDecodeError, OSError):
            continue

    return records, total_size
