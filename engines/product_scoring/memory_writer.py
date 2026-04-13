"""Product Scoring Engine — memory writer.

Persists scoring results to disk for future reference.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_scoring_result(
    scored_products: list[dict[str, Any]],
    score_distribution: dict[str, int],
    avg_composite_score: float,
) -> dict[str, Any]:
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "product_count": len(scored_products),
            "score_distribution": copy.deepcopy(score_distribution),
            "avg_composite_score": avg_composite_score,
            "top_products": [s.get("id", "") for s in scored_products[:5]],
        }
        _ensure_memory_dir()
        fpath = os.path.join(_MEMORY_DIR, f"{record_id}.json")
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, default=str)
        return {"status": "success", "record_id": record_id, "path": fpath}
    except Exception as exc:
        return {"status": "warning", "record_id": None, "path": None, "note": f"Memory write failed (non-fatal): {exc}"}


def _ensure_memory_dir() -> None:
    os.makedirs(_MEMORY_DIR, exist_ok=True)
