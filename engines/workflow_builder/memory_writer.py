"""Workflow Builder Engine — memory writer.

Persists workflow build results to disk for future reference.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_workflow_result(
    workflow: dict[str, Any],
    validation: dict[str, Any],
    execution_plan: dict[str, Any],
) -> dict[str, Any]:
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record: dict[str, Any] = {
            "record_id": record_id, "timestamp": timestamp,
            "workflow_id": workflow.get("id", ""),
            "step_count": len(workflow.get("steps_ordered", [])),
            "valid": validation.get("valid", False),
            "estimated_duration": execution_plan.get("estimated_duration_seconds", 0),
            "outcome_actual": None,
        }
        os.makedirs(_MEMORY_DIR, exist_ok=True)
        fpath = os.path.join(_MEMORY_DIR, f"{record_id}.json")
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, default=str)
        return {"status": "success", "record_id": record_id, "path": fpath}
    except Exception as exc:
        return {"status": "warning", "record_id": None, "path": None, "note": f"Memory write failed (non-fatal): {exc}"}
