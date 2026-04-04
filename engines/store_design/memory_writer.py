"""Store Design Engine — memory writer.

Persists store design decisions to disk for future reference.
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


def write_design_result(
    layout_recommendations: list[dict[str, Any]],
    color_palette: dict[str, Any],
    navigation: dict[str, Any],
    mobile_optimizations: list[dict[str, Any]],
    estimated_conversion_lift: float,
) -> dict[str, Any]:
    """Write a store design result record to memory.

    Args:
        layout_recommendations: List of layout recommendation dicts.
        color_palette: Color palette dict.
        navigation: Navigation structure dict.
        mobile_optimizations: List of mobile optimization dicts.
        estimated_conversion_lift: Estimated conversion lift percentage.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "layout_recommendations": copy.deepcopy(layout_recommendations),
            "color_palette": copy.deepcopy(color_palette),
            "navigation": copy.deepcopy(navigation),
            "mobile_optimizations": copy.deepcopy(mobile_optimizations),
            "estimated_conversion_lift": estimated_conversion_lift,
            "recommendations_count": len(layout_recommendations) + len(mobile_optimizations),
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
