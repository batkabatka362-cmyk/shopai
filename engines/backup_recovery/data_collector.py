"""Backup/Recovery Engine — data collector.

Collects data from .memory/ directories for each requested source.
Scans engine memory directories (products, orders, customers, settings)
and gathers all JSON records for backup.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

# Base path: project root
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Mapping of source names to their .memory/ directory locations
_SOURCE_PATHS: dict[str, list[str]] = {
    "products": [
        os.path.join(_PROJECT_ROOT, "engines", "inventory", ".memory"),
        os.path.join(_PROJECT_ROOT, ".memory", "products"),
    ],
    "orders": [
        os.path.join(_PROJECT_ROOT, "engines", "orders", ".memory"),
        os.path.join(_PROJECT_ROOT, ".memory", "orders"),
    ],
    "customers": [
        os.path.join(_PROJECT_ROOT, "engines", "customers", ".memory"),
        os.path.join(_PROJECT_ROOT, ".memory", "customers"),
    ],
    "settings": [
        os.path.join(_PROJECT_ROOT, ".memory", "settings"),
    ],
}


def collect_data(
    sources: list[str],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect data from .memory/ directories for each source.

    Args:
        sources: List of source names to collect (e.g. ["products", "orders"]).
        options: Optional collection options (reserved for future use).

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

        collected: dict[str, Any] = {}
        total_records = 0

        for source in sources:
            source_result = _collect_source(source)
            collected[source] = source_result
            total_records += source_result["count"]

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

def _collect_source(source: str) -> dict[str, Any]:
    """Collect all JSON records from a single source's memory directories."""
    records: list[dict[str, Any]] = []
    total_size = 0

    search_paths = _SOURCE_PATHS.get(source, [
        os.path.join(_PROJECT_ROOT, ".memory", source),
    ])

    for dir_path in search_paths:
        if not os.path.isdir(dir_path):
            continue

        for fname in sorted(os.listdir(dir_path)):
            if not fname.endswith(".json"):
                continue

            fpath = os.path.join(dir_path, fname)
            try:
                file_size = os.path.getsize(fpath)
                with open(fpath, "r", encoding="utf-8") as fh:
                    data = json.load(fh)

                if isinstance(data, dict):
                    data["_source_file"] = fname
                    data["_source_path"] = dir_path
                    records.append(data)
                    total_size += file_size
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            item["_source_file"] = fname
                            item["_source_path"] = dir_path
                            records.append(item)
                    total_size += file_size
            except (json.JSONDecodeError, OSError):
                continue

    return {
        "records": records,
        "count": len(records),
        "size_bytes": total_size,
    }
