"""International Expansion Engine — memory writer.

Persists expansion decisions to disk for future reference.
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


def write_expansion_result(
    market_scores: list[dict[str, Any]],
    currency_pricing: list[dict[str, Any]],
    localization_gaps: list[dict[str, Any]],
    shipping_plans: list[dict[str, Any]],
    recommended_markets: list[str],
) -> dict[str, Any]:
    """Write an expansion result record to memory.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "market_scores": copy.deepcopy(market_scores),
            "currency_pricing": copy.deepcopy(currency_pricing),
            "localization_gaps": copy.deepcopy(localization_gaps),
            "shipping_plans": copy.deepcopy(shipping_plans),
            "recommended_markets": copy.deepcopy(recommended_markets),
            "outcome_actual": None,
        }

        _ensure_memory_dir()
        fpath = os.path.join(_MEMORY_DIR, f"{record_id}.json")
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, default=str)

        return {"status": "success", "record_id": record_id, "path": fpath}
    except Exception as exc:
        return {
            "status": "warning", "record_id": None, "path": None,
            "note": f"Memory write failed (non-fatal): {exc}",
        }


def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
