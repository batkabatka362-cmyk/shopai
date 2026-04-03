"""Tax Engine — memory writer.

Persists tax calculation results and caches rates for future reference.
Each record is stored as a separate JSON file keyed by record_id.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_tax_record(
    transaction_id: str,
    tax_lines: list[dict[str, Any]],
    total_tax: float,
    jurisdictions: list[dict[str, Any]],
    report: dict[str, Any] | None = None,
    exemptions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write a tax calculation record to memory.

    Args:
        transaction_id: The transaction identifier.
        tax_lines: List of TaxLineItem dicts.
        total_tax: Total tax amount.
        jurisdictions: List of JurisdictionInfo dicts.
        report: Optional tax report dict.
        exemptions: Optional list of exemption results.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "transaction_id": str(transaction_id),
            "total_tax": round(float(total_tax), 2),
            "line_count": len(tax_lines),
            "tax_lines": copy.deepcopy(tax_lines),
            "jurisdictions": copy.deepcopy(jurisdictions),
            "report": copy.deepcopy(report) if report else {},
            "exemptions": copy.deepcopy(exemptions) if exemptions else [],
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
