"""Upsell Engine — memory writer.

Persists upsell performance records to disk for future reference.
Each run is stored as a separate JSON file keyed by record_id.
Used to track which upsells were recommended and their outcomes.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_upsell_result(
    upsells: list[dict[str, Any]],
    best_upsell: dict[str, Any] | None,
    estimated_revenue_increase: float,
    confidence: float,
    current_product_id: str,
    current_price: float,
    category: str,
    candidates_evaluated: int,
    candidates_recommended: int,
) -> dict[str, Any]:
    """Write an upsell result record to memory.

    Args:
        upsells: List of UpsellRecommendation dicts.
        best_upsell: The top recommendation (or None).
        estimated_revenue_increase: Total expected revenue increase.
        confidence: Overall confidence score.
        current_product_id: The product being upsold from.
        current_price: Current product price.
        category: Product category.
        candidates_evaluated: Number of catalog candidates evaluated.
        candidates_recommended: Number of final recommendations.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "current_product_id": str(current_product_id),
            "current_price": round(float(current_price), 2),
            "category": str(category),
            "candidates_evaluated": int(candidates_evaluated),
            "candidates_recommended": int(candidates_recommended),
            "estimated_revenue_increase": round(float(estimated_revenue_increase), 2),
            "confidence": round(float(confidence), 4),
            "best_upsell_id": (
                str(best_upsell.get("product_id", ""))
                if best_upsell else None
            ),
            "best_upsell_expected_revenue": (
                round(float(best_upsell.get("expected_revenue", 0.0)), 2)
                if best_upsell else 0.0
            ),
            "upsell_ids": [
                str(u.get("product_id", "")) for u in upsells
            ],
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
