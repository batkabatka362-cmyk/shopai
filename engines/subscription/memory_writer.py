"""Subscription Engine — memory writer.

Persists subscription analysis results to disk for future reference.
Each run is stored as a separate JSON file keyed by record_id.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_subscription_result(
    plan_recommendations: list[dict[str, Any]],
    billing_summary: dict[str, Any],
    churn_risks: list[dict[str, Any]],
    upgrade_opportunities: list[dict[str, Any]],
    mrr: float,
) -> dict[str, Any]:
    """Write a subscription result record to memory.

    Args:
        plan_recommendations: List of plan recommendation dicts.
        billing_summary: Billing summary dict.
        churn_risks: List of churn risk dicts.
        upgrade_opportunities: List of upgrade opportunity dicts.
        mrr: Monthly recurring revenue.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "plan_count": len(plan_recommendations),
            "active_subscriptions": billing_summary.get("active_subscriptions", 0),
            "churn_risk_count": len(churn_risks),
            "upgrade_opportunity_count": len(upgrade_opportunities),
            "mrr": mrr,
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
