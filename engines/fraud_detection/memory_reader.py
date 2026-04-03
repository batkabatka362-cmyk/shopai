"""Fraud Detection Engine — memory reader.

Reads past fraud decision records from memory storage.
Used to provide historical context for velocity checks and pattern detection.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory", "fraud_detection")


def read_fraud_history(
    email: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Read past fraud decision records from memory.

    Args:
        email: Optional email to filter records by.
        limit: Max records to return.

    Returns:
        Structured dict with past records and count.
    """
    try:
        records = _load_records()

        # Filter by email if provided
        if email:
            email_norm = email.lower().strip()
            records = [
                r for r in records
                if str(r.get("email", "")).lower().strip() == email_norm
            ]

        # Sort by timestamp descending (most recent first)
        records = sorted(
            records,
            key=lambda r: r.get("timestamp", ""),
            reverse=True,
        )[:limit]

        return {
            "status": "success",
            "records": copy.deepcopy(records),
            "count": len(records),
        }
    except Exception as exc:
        return {
            "status": "success",
            "records": [],
            "count": 0,
            "note": f"Memory read warning: {exc}",
        }


def read_past_orders(
    email: str | None = None,
    ip: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Read past order summaries for velocity and pattern checks.

    Args:
        email: Optional email filter.
        ip: Optional IP filter.
        limit: Max records to return.

    Returns:
        List of simplified order dicts from past fraud records.
    """
    try:
        records = _load_records()
        orders: list[dict[str, Any]] = []

        for record in records:
            order_summary = record.get("order_summary", {})
            if not order_summary:
                continue

            rec_email = str(order_summary.get("email", "")).lower().strip()
            rec_ip = str(order_summary.get("ip_address", "")).strip()

            match = False
            if email and rec_email == email.lower().strip():
                match = True
            if ip and rec_ip == ip.strip():
                match = True
            if not email and not ip:
                match = True

            if match:
                orders.append(copy.deepcopy(order_summary))

        # Sort by timestamp descending
        orders.sort(key=lambda o: o.get("created_at", ""), reverse=True)
        return orders[:limit]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_records() -> list[dict[str, Any]]:
    """Load all fraud decision records from the memory directory."""
    if not os.path.isdir(_MEMORY_DIR):
        return []

    records: list[dict[str, Any]] = []
    for fname in os.listdir(_MEMORY_DIR):
        if not fname.endswith(".json") or fname == "blacklists.json":
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
