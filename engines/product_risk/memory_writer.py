"""Product Risk Engine — memory writer.

Persists risk assessment results to disk for future reference.
Each run is stored as a separate JSON file keyed by record_id.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_risk_result(
    risks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write a risk assessment result record to memory.

    Args:
        risks: List of per-product risk assessment dicts.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        overall_scores = [r.get("overall", 0.0) for r in risks]
        avg_overall = round(sum(overall_scores) / len(overall_scores), 3) if overall_scores else 0.0

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "risks": copy.deepcopy(risks),
            "product_count": len(risks),
            "avg_overall_risk": avg_overall,
            "outcome_actual": None,
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
