"""Meta-Intelligence Governance -- memory reader.

Reads past governance history from memory storage.
Used to inform current governance decisions with historical context.

Model note: Would use Qwen for structured retrieval and filtering.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_governance_history(
    source_engine: str = "",
    action_type: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Read past governance records, optionally filtered.

    Args:
        source_engine: Filter by source engine (empty = all).
        action_type: Filter by action type (empty = all).
        limit: Max records to return.

    Returns:
        Structured dict with past governance records and summary.
    """
    try:
        records = _load_records()

        if source_engine:
            records = [
                r for r in records
                if r.get("source_engine", "") == source_engine
            ]

        if action_type:
            records = [
                r for r in records
                if r.get("action_type", "") == action_type
            ]

        records = sorted(
            records,
            key=lambda r: r.get("timestamp", ""),
            reverse=True,
        )[:limit]

        summary = _compute_summary(records)

        return {
            "status": "success",
            "records": copy.deepcopy(records),
            "count": len(records),
            "summary": summary,
        }
    except Exception as exc:
        return {
            "status": "success",
            "records": [],
            "count": 0,
            "summary": {},
            "note": f"Memory read warning: {exc}",
        }


def get_recent_rejection_count(
    source_engine: str = "",
    action_type: str = "",
    limit: int = 50,
) -> int:
    """Count recent rejections for a given engine/action.

    Useful for detecting patterns of repeated bad behavior.
    """
    result = read_governance_history(
        source_engine=source_engine,
        action_type=action_type,
        limit=limit,
    )
    records = result.get("records", [])
    return sum(1 for r in records if r.get("decision") == "rejected")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_records() -> list[dict[str, Any]]:
    """Load all governance records from the memory directory."""
    if not os.path.isdir(_MEMORY_DIR):
        return []

    records: list[dict[str, Any]] = []
    for fname in os.listdir(_MEMORY_DIR):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(_MEMORY_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    records.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return records


def _compute_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary statistics over governance records."""
    if not records:
        return {
            "total_records": 0,
            "approval_rate": 0.0,
            "avg_risk_score": 0.0,
            "avg_validation_score": 0.0,
            "decision_distribution": {},
        }

    n = len(records)
    decisions = [r.get("decision", "unknown") for r in records]
    decision_dist: dict[str, int] = {}
    for d in decisions:
        decision_dist[d] = decision_dist.get(d, 0) + 1

    approved = sum(
        1 for d in decisions
        if d in ("approved", "approved_with_warning", "modified")
    )
    approval_rate = approved / n if n > 0 else 0.0

    risk_scores = [float(r.get("risk_score", 0.0)) for r in records]
    avg_risk = sum(risk_scores) / n if n > 0 else 0.0

    val_scores = [float(r.get("validation_score", 0.0)) for r in records]
    avg_val = sum(val_scores) / n if n > 0 else 0.0

    return {
        "total_records": n,
        "approval_rate": round(approval_rate, 4),
        "avg_risk_score": round(avg_risk, 4),
        "avg_validation_score": round(avg_val, 4),
        "decision_distribution": decision_dist,
    }
