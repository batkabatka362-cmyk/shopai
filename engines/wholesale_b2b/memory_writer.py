"""Wholesale B2B Engine — memory writer.

Persists wholesale decisions to disk for future reference.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_wholesale_result(
    tiers: list[dict[str, Any]],
    account_status: list[dict[str, Any]],
    volume_discounts: list[dict[str, Any]],
    processed_orders: list[dict[str, Any]],
    credit_terms: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write a wholesale result record to memory."""
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "tiers": copy.deepcopy(tiers),
            "account_status": copy.deepcopy(account_status),
            "volume_discounts": copy.deepcopy(volume_discounts),
            "processed_orders": copy.deepcopy(processed_orders),
            "credit_terms": copy.deepcopy(credit_terms),
            "outcome_actual": None,
        }
        _ensure_memory_dir()
        fpath = os.path.join(_MEMORY_DIR, f"{record_id}.json")
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, default=str)
        return {"status": "success", "record_id": record_id, "path": fpath}
    except Exception as exc:
        return {"status": "warning", "record_id": None, "path": None, "note": f"Memory write failed (non-fatal): {exc}"}


def _ensure_memory_dir() -> None:
    os.makedirs(_MEMORY_DIR, exist_ok=True)
