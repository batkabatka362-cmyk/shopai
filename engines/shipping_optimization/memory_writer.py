"""Shipping Optimization Engine — memory writer.

Persists shipping decisions to disk for future reference.
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


def write_shipping_result(
    recommended_strategy: dict[str, Any],
    free_shipping_threshold: float,
    estimated_savings_monthly: float,
    carrier_comparison_count: int,
    confidence: float,
    input_hash: str = "",
) -> dict[str, Any]:
    """Write a shipping optimization result record to memory.

    Args:
        recommended_strategy: The winning strategy dict.
        free_shipping_threshold: Optimized free-shipping threshold.
        estimated_savings_monthly: Projected monthly savings.
        carrier_comparison_count: Number of carriers compared.
        confidence: Overall confidence score.
        input_hash: Hash of the input payload for dedup.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "recommended_strategy": copy.deepcopy(recommended_strategy),
            "free_shipping_threshold": round(float(free_shipping_threshold), 2),
            "estimated_savings_monthly": round(float(estimated_savings_monthly), 2),
            "carrier_comparison_count": int(carrier_comparison_count),
            "confidence": round(float(confidence), 4),
            "input_hash": str(input_hash),
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


def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
