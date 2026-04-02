"""Simulation Lab — memory writer.

Persists simulation results to disk for future reference.
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


def write_simulation_result(
    strategy_type: str,
    input_hash: str,
    best_option: dict[str, Any],
    all_scenarios: list[dict[str, Any]],
    confidence: float,
) -> dict[str, Any]:
    """Write a simulation result record to memory.

    Args:
        strategy_type: The type of strategy that was simulated.
        input_hash: Hash of the original input (for dedup).
        best_option: The selected best option dict.
        all_scenarios: All scenario summaries.
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
            "strategy_type": strategy_type,
            "input_hash": input_hash,
            "best_option": copy.deepcopy(best_option),
            "all_scenarios": copy.deepcopy(all_scenarios),
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
