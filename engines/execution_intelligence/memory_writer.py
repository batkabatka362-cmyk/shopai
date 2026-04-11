"""Execution Intelligence — memory writer.

Persists execution results to disk for future reference.
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


def write_execution_result(
    input_hash: str,
    status_report: dict[str, Any],
    executed: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    results: list[dict[str, Any]],
    logs: list[str],
) -> dict[str, Any]:
    """Write an execution result record to memory.

    Args:
        input_hash: Hash of the original input (for dedup).
        status_report: The status report dict.
        executed: List of executed task summaries.
        failed: List of failed task summaries.
        results: List of task result dicts.
        logs: Execution log lines.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        report = copy.deepcopy(status_report)

        action_types: list[str] = []
        for entry in executed:
            atype = entry.get("type", "unknown")
            if atype not in action_types:
                action_types.append(atype)
        for entry in failed:
            atype = entry.get("type", "unknown")
            if atype not in action_types:
                action_types.append(atype)

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "input_hash": input_hash,
            "action_types": action_types,
            "total_tasks": int(report.get("total_tasks", 0)),
            "success_count": int(report.get("succeeded", 0)),
            "fail_count": int(report.get("failed", 0)),
            "overall_status": report.get("overall_status", "unknown"),
            "success_rate": float(report.get("success_rate", 0.0)),
            "results": copy.deepcopy(results),
            "logs": list(logs),
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
