"""Content Generation Engine — memory writer.

Persists generated content records to disk for future reference and
performance tracking. Each run is stored as a separate JSON file.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_content_result(
    content: dict[str, Any],
    seo_score: float,
    readability_score: float,
    content_type: str,
    platform: str,
    confidence: float,
    variation_count: int,
) -> dict[str, Any]:
    """Write a content generation result record to memory.

    Args:
        content: The generated ContentBlock dict.
        seo_score: SEO score (0.0 to 1.0).
        readability_score: Flesch reading ease score.
        content_type: Type of content generated.
        platform: Target platform.
        confidence: Overall confidence score.
        variation_count: Number of variations generated.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "content_type": content_type,
            "platform": platform,
            "headline": str(content.get("headline", "")),
            "seo_score": round(seo_score, 2),
            "readability_score": round(readability_score, 2),
            "confidence": round(confidence, 2),
            "variation_count": variation_count,
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
