"""Accounting Engine — memory writer.

Persists journal entries, updated balances, and reports to disk.
Each run is stored as a separate JSON file keyed by record_id.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory", "accounting")


def write_accounting_record(
    journal_entries: list[dict[str, Any]],
    balances: dict[str, Any],
    report: dict[str, Any] | None = None,
    reconciliation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write an accounting result record to memory.

    Args:
        journal_entries: List of JournalEntry dicts to persist.
        balances: Balance calculator result dict.
        report: Optional generated report dict.
        reconciliation: Optional reconciliation result dict.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "journal_entries": copy.deepcopy(journal_entries),
            "balances": copy.deepcopy(balances.get("balances", {})),
            "is_balanced": balances.get("is_balanced", False),
            "total_debits": balances.get("total_debits", 0.0),
            "total_credits": balances.get("total_credits", 0.0),
            "entry_count": len(journal_entries),
        }

        if report:
            record["report"] = copy.deepcopy(report)

        if reconciliation:
            record["reconciliation"] = copy.deepcopy(reconciliation)

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
