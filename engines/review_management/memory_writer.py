"""Review Management Engine — memory writer.

Persists review analysis results to disk for future reference.
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


def write_review_analysis(
    product_id: str,
    avg_rating: float,
    total_reviews: int,
    sentiment_summary: dict[str, Any],
    trend_direction: str,
    top_insights: list[dict[str, Any]],
    confidence: float,
) -> dict[str, Any]:
    """Write a review analysis record to memory.

    Args:
        product_id: The product identifier.
        avg_rating: Overall average rating.
        total_reviews: Total number of reviews analyzed.
        sentiment_summary: Aggregate sentiment percentages.
        trend_direction: Rating trend direction.
        top_insights: Top insight items.
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
            "product_id": str(product_id),
            "avg_rating": round(float(avg_rating), 2),
            "total_reviews": int(total_reviews),
            "sentiment_summary": copy.deepcopy(sentiment_summary),
            "trend_direction": str(trend_direction),
            "top_insights": copy.deepcopy(top_insights[:5]),
            "confidence": round(float(confidence), 4),
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
