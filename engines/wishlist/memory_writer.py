"""Wishlist Engine — memory writer."""
from __future__ import annotations
import json, os, time, uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")

def write_wishlist_result(analysis: dict[str, Any], recommendations_count: int) -> dict[str, Any]:
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record = {
            "record_id": record_id, "timestamp": timestamp,
            "total_wishlists": analysis.get("total_wishlists", 0),
            "recommendations_count": recommendations_count,
            "outcome_actual": None,
        }
        _ensure_memory_dir()
        fpath = os.path.join(_MEMORY_DIR, f"{record_id}.json")
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, default=str)
        return {"status": "success", "record_id": record_id, "path": fpath}
    except Exception as exc:
        return {"status": "warning", "record_id": None, "note": f"Memory write failed (non-fatal): {exc}"}

def _ensure_memory_dir() -> None:
    os.makedirs(_MEMORY_DIR, exist_ok=True)
