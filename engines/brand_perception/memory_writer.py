"""Brand Perception Engine — memory writer.

Persists brand perception results to disk for future reference.
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


def write_perception_result(
    mention_count: int,
    sentiment: dict[str, Any],
    reputation_score: int,
    trends: list[str],
    threats: list[str],
    opportunities: list[str],
) -> dict[str, Any]:
    """Write a brand perception result record to memory.

    Args:
        mention_count: Total mention count.
        sentiment: Sentiment breakdown dict.
        reputation_score: Reputation score 0-100.
        trends: List of trend strings.
        threats: List of threat strings.
        opportunities: List of opportunity strings.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "mention_count": mention_count,
            "sentiment": copy.deepcopy(sentiment),
            "reputation_score": reputation_score,
            "trends": list(trends),
            "threats": list(threats),
            "opportunities": list(opportunities),
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
