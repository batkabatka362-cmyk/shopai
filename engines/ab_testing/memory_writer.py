"""A/B Testing -- memory writer.

Persists A/B test results to disk for future reference.
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


def write_test_result(
    experiment: dict[str, Any],
    winner: dict[str, Any],
    analysis: dict[str, Any],
    test_type: str,
    confidence: float,
    input_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write an A/B test result record to memory.

    Args:
        experiment: Experiment design dict.
        winner: Winner selection result dict.
        analysis: Statistical analysis result dict.
        test_type: Category of test.
        confidence: Overall confidence score.
        input_data: Original input data (for input hash).

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Compute input hash for deduplication
        input_hash = ""
        if input_data:
            import hashlib
            serialized = json.dumps(input_data, sort_keys=True, default=str)
            input_hash = hashlib.sha256(serialized.encode()).hexdigest()[:16]

        # Serialize confidence interval tuple to list for JSON
        analysis_copy = copy.deepcopy(analysis)
        ci = analysis_copy.get("confidence_interval")
        if isinstance(ci, tuple):
            analysis_copy["confidence_interval"] = list(ci)

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "test_type": str(test_type),
            "input_hash": input_hash,
            "experiment": copy.deepcopy(experiment),
            "winner": copy.deepcopy(winner),
            "analysis": analysis_copy,
            "confidence": round(float(confidence), 4),
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
