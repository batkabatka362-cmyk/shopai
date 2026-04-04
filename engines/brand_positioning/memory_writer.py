"""Brand Positioning Engine — memory writer.

Persists brand positioning results to disk for future reference.
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


def write_positioning_result(
    position_map: dict[str, Any],
    gaps: list[dict[str, Any]],
    differentiation_scores: list[dict[str, Any]],
    strategy_recommendations: list[dict[str, Any]],
    competitive_advantages: list[str],
) -> dict[str, Any]:
    """Write a brand positioning result record to memory.

    Args:
        position_map: Position map dict.
        gaps: Market gap dicts.
        differentiation_scores: Differentiation score dicts.
        strategy_recommendations: Strategy recommendation dicts.
        competitive_advantages: List of competitive advantage strings.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "position_map": copy.deepcopy(position_map),
            "gaps_count": len(gaps),
            "differentiation_scores_count": len(differentiation_scores),
            "strategy_count": len(strategy_recommendations),
            "competitive_advantages": list(competitive_advantages),
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
