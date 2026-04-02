"""Learning Loop — memory writer.

Persists learning results to disk for future reference.
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


def write_learning_result(
    task: str,
    decision: str,
    execution: str,
    result: dict[str, Any],
    performance: str,
    score: float,
    errors: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    insights: list[dict[str, Any]],
    improvements: list[dict[str, Any]],
    confidence: float,
) -> dict[str, Any]:
    """Write a learning result record to memory.

    Args:
        task: The task that was executed.
        decision: The decision that led to execution.
        execution: Description of what was executed.
        result: Raw result metrics.
        performance: Performance classification label.
        score: Overall performance score 0-1.
        errors: Detected errors list.
        patterns: Detected patterns list.
        insights: Generated insights list.
        improvements: Improvement suggestions list.
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
            "task": task,
            "decision": decision,
            "execution": execution,
            "result": copy.deepcopy(result),
            "performance": performance,
            "score": round(score, 4),
            "errors": copy.deepcopy(errors),
            "patterns": copy.deepcopy(patterns),
            "insights": copy.deepcopy(insights),
            "improvements": copy.deepcopy(improvements),
            "confidence": round(confidence, 4),
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
