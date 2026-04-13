"""Search Optimization Engine — memory writer.

Persists search optimization results to disk for future reference.
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


def write_optimization_result(
    keyword_analysis: list[dict[str, Any]],
    meta_recommendations: list[dict[str, Any]],
    content_scores: list[dict[str, Any]],
    sitemap: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write a search optimization result record to memory.

    Args:
        keyword_analysis: List of keyword analysis dicts.
        meta_recommendations: List of meta recommendation dicts.
        content_scores: List of content score dicts.
        sitemap: List of sitemap entry dicts.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "keyword_analysis": copy.deepcopy(keyword_analysis),
            "meta_recommendations": copy.deepcopy(meta_recommendations),
            "content_scores": copy.deepcopy(content_scores),
            "sitemap_size": len(sitemap),
            "keyword_count": len(keyword_analysis),
            "product_count": len(meta_recommendations),
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
