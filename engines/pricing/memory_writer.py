"""Pricing Engine — memory writer.

Persists pricing decisions to disk for future reference.
Each run is stored as a separate JSON file keyed by record_id.

Model note: Would use Qwen for structured serialization.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_pricing_result(
    recommended_price: float,
    strategy: str,
    projected_margin: float,
    cost_breakdown: dict[str, Any],
    competitive_position: str,
    confidence: float,
) -> dict[str, Any]:
    """Write a pricing result record to memory.

    Args:
        recommended_price: The final recommended price.
        strategy: Pricing strategy used.
        projected_margin: Margin at the recommended price.
        cost_breakdown: Full cost breakdown dict.
        competitive_position: Position relative to market.
        confidence: Overall confidence score.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "recommended_price": round(float(recommended_price), 2),
            "strategy": str(strategy),
            "projected_margin": round(float(projected_margin), 4),
            "cost_breakdown": copy.deepcopy(cost_breakdown),
            "competitive_position": str(competitive_position),
            "confidence": round(float(confidence), 4),
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
