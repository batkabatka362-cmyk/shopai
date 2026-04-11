"""Profit Optimization Engine — memory writer.

Persists optimization results to disk for future reference.
Each run is stored as a separate JSON file keyed by record_id.

Model note: Would use Qwen for structured serialization.
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
    profit_metrics: dict[str, Any],
    kpis: dict[str, Any],
    selected_strategy: dict[str, Any],
    recommended_actions: list[dict[str, Any]],
    confidence: float,
) -> dict[str, Any]:
    """Write an optimization result record to memory.

    Args:
        profit_metrics: Computed profit metrics.
        kpis: Computed KPI results.
        selected_strategy: The selected strategy dict.
        recommended_actions: List of action recommendations.
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
            "profit_metrics": copy.deepcopy(profit_metrics),
            "kpis": copy.deepcopy(kpis),
            "selected_strategy": copy.deepcopy(selected_strategy),
            "recommended_actions": copy.deepcopy(recommended_actions),
            "confidence": round(confidence, 4),
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
