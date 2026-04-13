"""Sentiment Analysis Engine — memory reader.

Reads past sentiment analysis records from memory storage.
Used to inform current analysis with historical context.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_sentiments(
    limit: int = 10,
) -> dict[str, Any]:
    """Read past sentiment analysis records.

    Args:
        limit: Max records to return.

    Returns:
        Structured dict with past records and summary statistics.
    """
    try:
        records = _load_records()

        records = sorted(
            records,
            key=lambda r: r.get("timestamp", ""),
            reverse=True,
        )[:limit]

        summary = _compute_summary(records)

        return {
            "status": "success",
            "records": copy.deepcopy(records),
            "count": len(records),
            "summary": summary,
        }
    except Exception as exc:
        return {
            "status": "success",
            "records": [],
            "count": 0,
            "summary": {},
            "note": f"Memory read warning: {exc}",
        }


def compute_input_hash(input_data: dict[str, Any]) -> str:
    """Produce a deterministic hash for an input payload."""
    try:
        serialised = json.dumps(input_data, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_records() -> list[dict[str, Any]]:
    """Load all records from the memory directory."""
    if not os.path.isdir(_MEMORY_DIR):
        return []

    records: list[dict[str, Any]] = []
    for fname in os.listdir(_MEMORY_DIR):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(_MEMORY_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    records.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return records


def _compute_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary statistics over past sentiment analysis records."""
    if not records:
        return {
            "avg_overall_sentiment": 0.0,
            "avg_topic_count": 0.0,
            "total_runs": 0,
        }

    sentiments = [float(r.get("overall_sentiment", 0)) for r in records]
    topic_counts = [len(r.get("topics", [])) for r in records]

    n = len(records)
    return {
        "avg_overall_sentiment": round(sum(sentiments) / n, 4) if n else 0.0,
        "avg_topic_count": round(sum(topic_counts) / n, 1) if n else 0.0,
        "total_runs": n,
    }
