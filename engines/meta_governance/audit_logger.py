"""Meta-Intelligence Governance -- audit logger.

Logs all governance decisions for audit trail.
Every decision that passes through the governance engine is recorded.

Model note: Pure I/O — no model needed.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_AUDIT_DIR = os.path.join(os.path.dirname(__file__), ".audit")


def log_audit_entry(
    activity: dict[str, Any],
    decision: str,
    violations: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    risk_score: float,
    override_applied: bool,
    modifications: dict[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    """Log a governance decision to the audit trail.

    Args:
        activity: SystemActivity dict.
        decision: Final decision string.
        violations: Rule violations found.
        risks: Risk assessments.
        risk_score: Overall risk score.
        override_applied: Whether an override was applied.
        modifications: Any modifications made.
        elapsed_seconds: Time taken for governance.

    Returns:
        Structured dict confirming the audit log.
    """
    try:
        entry_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        entry: dict[str, Any] = {
            "entry_id": entry_id,
            "timestamp": timestamp,
            "activity_id": activity.get("activity_id", "unknown"),
            "source_engine": activity.get("source_engine", "unknown"),
            "action_type": activity.get("action_type", "unknown"),
            "decision": decision,
            "violations": copy.deepcopy(violations),
            "risks": copy.deepcopy(risks),
            "risk_score": round(risk_score, 4),
            "override_applied": override_applied,
            "modifications": copy.deepcopy(modifications),
            "elapsed_seconds": round(elapsed_seconds, 3),
        }

        _ensure_audit_dir()
        fpath = os.path.join(_AUDIT_DIR, f"{entry_id}.json")
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(entry, fh, indent=2, default=str)

        return {
            "status": "success",
            "entry_id": entry_id,
            "path": fpath,
        }
    except Exception as exc:
        return {
            "status": "warning",
            "entry_id": None,
            "path": None,
            "note": f"Audit log failed (non-fatal): {exc}",
        }


def read_audit_trail(
    source_engine: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Read recent audit entries, optionally filtered by engine.

    Args:
        source_engine: Filter by source engine (empty = all).
        limit: Max entries to return.

    Returns:
        Structured dict with audit entries.
    """
    try:
        entries = _load_entries()

        if source_engine:
            entries = [
                e for e in entries
                if e.get("source_engine", "") == source_engine
            ]

        entries = sorted(
            entries,
            key=lambda e: e.get("timestamp", ""),
            reverse=True,
        )[:limit]

        return {
            "status": "success",
            "entries": entries,
            "count": len(entries),
        }
    except Exception as exc:
        return {
            "status": "success",
            "entries": [],
            "count": 0,
            "note": f"Audit read warning: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_audit_dir() -> None:
    """Create the audit directory if it doesn't exist."""
    os.makedirs(_AUDIT_DIR, exist_ok=True)


def _load_entries() -> list[dict[str, Any]]:
    """Load all audit entries from disk."""
    if not os.path.isdir(_AUDIT_DIR):
        return []

    entries: list[dict[str, Any]] = []
    for fname in os.listdir(_AUDIT_DIR):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(_AUDIT_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    entries.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return entries
