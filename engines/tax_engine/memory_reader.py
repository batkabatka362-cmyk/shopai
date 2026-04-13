"""Tax Engine — memory reader.

Reads cached tax rate lookups and past calculation records from memory.
Used to speed up repeated calculations for the same jurisdictions.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_tax_cache(
    jurisdiction_code: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Read cached tax rate lookups.

    Args:
        jurisdiction_code: Optional filter by jurisdiction code.
        limit: Max records to return.

    Returns:
        Structured dict with cached rates and count.
    """
    try:
        records = _load_records()

        # Filter by jurisdiction if specified
        if jurisdiction_code:
            records = [
                r for r in records
                if _matches_jurisdiction(r, jurisdiction_code)
            ]

        # Sort by timestamp descending
        records = sorted(
            records,
            key=lambda r: r.get("timestamp", ""),
            reverse=True,
        )[:limit]

        return {
            "status": "success",
            "cached_rates": copy.deepcopy(records),
            "count": len(records),
        }
    except Exception as exc:
        return {
            "status": "success",
            "cached_rates": [],
            "count": 0,
            "note": f"Memory read warning: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_records() -> list[dict[str, Any]]:
    """Load all records from the memory directory."""
    if not os.path.isdir(_MEMORY_DIR):
        return []

    records: list[dict[str, Any]] = []
    for fname in os.listdir(_MEMORY_DIR):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(_MEMORY_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    records.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return records


def _matches_jurisdiction(
    record: dict[str, Any],
    jurisdiction_code: str,
) -> bool:
    """Check if a record matches the given jurisdiction code."""
    # Check in jurisdictions list
    for jur in record.get("jurisdictions", []):
        if str(jur.get("code", "")) == jurisdiction_code:
            return True
        if str(jur.get("name", "")) == jurisdiction_code:
            return True
    # Check filing jurisdiction in report
    report = record.get("report", {})
    if str(report.get("filing_jurisdiction", "")) == jurisdiction_code:
        return True
    return False
