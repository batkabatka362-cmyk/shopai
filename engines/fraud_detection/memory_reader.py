"""Fraud Detection Engine — memory reader.

Reads past fraud decisions and order history from .memory/fraud_detection/
for velocity checking and pattern detection.
"""
from __future__ import annotations

import json
import os
from typing import Any


_MEMORY_DIR = os.path.join(".memory", "fraud_detection")
_DECISIONS_FILE = os.path.join(_MEMORY_DIR, "decisions.json")


def read_fraud_history(
    email: str | None = None,
    ip: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Read past fraud decisions, optionally filtered by email or IP.

    Args:
        email: Filter by customer email.
        ip: Filter by IP address.
        limit: Maximum records to return.

    Returns:
        Dict with status, records, count.
    """
    try:
        records: list[dict[str, Any]] = []

        if os.path.isfile(_DECISIONS_FILE):
            with open(_DECISIONS_FILE, "r") as fh:
                all_records = json.load(fh)
            if not isinstance(all_records, list):
                all_records = []
        else:
            all_records = []

        # Filter
        for rec in all_records:
            if email and rec.get("email", "").lower() != email.lower():
                continue
            if ip and rec.get("ip_address", "") != ip:
                continue
            records.append(rec)

        # Sort by timestamp descending and limit
        records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        records = records[:limit]

        return {
            "status": "success",
            "records": records,
            "count": len(records),
        }

    except Exception as exc:
        return {
            "status": "success",
            "records": [],
            "count": 0,
            "note": f"Memory read warning: {exc}",
        }
