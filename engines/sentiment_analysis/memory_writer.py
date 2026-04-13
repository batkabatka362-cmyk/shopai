"""Sentiment Analysis Engine — memory writer.

Persists sentiment analysis results to disk for future reference.
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


def write_sentiment_result(
    overall_sentiment: float,
    sentiment_distribution: dict[str, Any],
    topics: list[dict[str, Any]],
    trends: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write a sentiment analysis result record to memory.

    Args:
        overall_sentiment: Overall sentiment score.
        sentiment_distribution: Distribution of sentiments.
        topics: List of extracted topic dicts.
        trends: List of sentiment trend dicts.
        alerts: List of alert dicts.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "overall_sentiment": overall_sentiment,
            "sentiment_distribution": copy.deepcopy(sentiment_distribution),
            "topics": copy.deepcopy(topics),
            "trends": copy.deepcopy(trends),
            "alerts_count": len(alerts),
            "topic_count": len(topics),
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
