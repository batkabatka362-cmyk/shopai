"""Fraud Detection Engine — memory writer.

Persists fraud decisions to disk for future reference.
Each run is stored as a separate JSON file keyed by record_id.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory", "fraud_detection")


def write_fraud_decision(
    order_id: str,
    verdict: str,
    risk_score: float,
    signals: dict[str, Any],
    order_summary: dict[str, Any] | None = None,
    alert: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a fraud decision record to memory.

    Args:
        order_id: The order identifier.
        verdict: The fraud verdict (approve, review, reject).
        risk_score: The final risk score (0.0-1.0).
        signals: Dict of all signal results.
        order_summary: Simplified order data for future velocity checks.
        alert: Alert dict if one was generated, else None.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "order_id": order_id,
            "verdict": verdict,
            "risk_score": round(risk_score, 4),
            "signals_summary": _summarize_signals(signals),
            "order_summary": copy.deepcopy(order_summary) if order_summary else {},
            "alert": copy.deepcopy(alert) if alert else None,
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _summarize_signals(signals: dict[str, Any]) -> dict[str, Any]:
    """Create a compact summary of signal scores for storage."""
    summary: dict[str, Any] = {}
    for name, data in signals.items():
        if isinstance(data, dict):
            summary[name] = {
                "score": data.get("score", 0.0),
                "status": data.get("status", "unknown"),
            }
    return summary


def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
