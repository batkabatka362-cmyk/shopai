"""Meta-Intelligence Governance -- memory writer.

Persists governance records to disk for future reference.
Each governance decision is stored as a separate JSON file.

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


def write_governance_record(
    activity: dict[str, Any],
    decision: str,
    issues: list[str],
    risks: list[dict[str, Any]],
    risk_score: float,
    violations: list[dict[str, Any]],
    override_applied: bool,
    modifications: dict[str, Any],
    validation_score: float,
    feedback: dict[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    """Write a governance decision record to memory.

    Args:
        activity: SystemActivity dict.
        decision: Final decision string.
        issues: List of issue strings.
        risks: Risk assessments.
        risk_score: Overall risk score.
        violations: Rule violations.
        override_applied: Whether override was applied.
        modifications: Any modifications made.
        validation_score: Validation score.
        feedback: System feedback dict.
        elapsed_seconds: Processing time.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "source_engine": activity.get("source_engine", "unknown"),
            "action_type": activity.get("action_type", "unknown"),
            "activity_id": activity.get("activity_id", "unknown"),
            "decision": decision,
            "issues": copy.deepcopy(issues),
            "risks": copy.deepcopy(risks),
            "risk_score": round(risk_score, 4),
            "violations": copy.deepcopy(violations),
            "override_applied": override_applied,
            "modifications": copy.deepcopy(modifications),
            "validation_score": round(validation_score, 4),
            "feedback_summary": {
                "recommendations": feedback.get("recommendations", []),
                "governance_confidence": feedback.get("governance_confidence", 0.0),
            },
            "elapsed_seconds": round(elapsed_seconds, 3),
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
