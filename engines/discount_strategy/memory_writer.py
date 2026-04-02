"""Discount Strategy Engine — memory writer.

Persists discount strategy decisions to disk for future reference.
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


def write_discount_result(
    strategy: dict[str, Any],
    margin_impact: dict[str, Any],
    projected_revenue: dict[str, Any],
    cannibalization_risk: str,
    confidence: float,
    goal: str,
    products_count: int,
) -> dict[str, Any]:
    """Write a discount strategy result record to memory.

    Args:
        strategy: The DiscountStrategy dict.
        margin_impact: The MarginImpact dict.
        projected_revenue: The ProjectedRevenue dict.
        cannibalization_risk: Risk level string.
        confidence: Overall confidence score.
        goal: Business goal that drove the strategy.
        products_count: Number of products evaluated.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "goal": str(goal),
            "products_count": int(products_count),
            "strategy": copy.deepcopy(strategy),
            "margin_impact": copy.deepcopy(margin_impact),
            "projected_revenue": copy.deepcopy(projected_revenue),
            "cannibalization_risk": str(cannibalization_risk),
            "confidence": round(float(confidence), 4),
            "outcome_actual": None,  # to be filled by feedback loop
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
