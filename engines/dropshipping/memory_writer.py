"""Dropshipping Engine — memory writer."""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_dropshipping_result(
    supplier_orders: list[dict[str, Any]],
    tracking_updates: list[dict[str, Any]],
    margin_analysis: list[dict[str, Any]],
    supplier_performance: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record: dict[str, Any] = {
            "record_id": record_id, "timestamp": timestamp,
            "supplier_orders": copy.deepcopy(supplier_orders),
            "tracking_updates": copy.deepcopy(tracking_updates),
            "margin_analysis": copy.deepcopy(margin_analysis),
            "supplier_performance": copy.deepcopy(supplier_performance),
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
