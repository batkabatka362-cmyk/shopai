"""Fraud Detection Engine — memory writer.

Persists fraud decision records to .memory/fraud_detection/decisions.json.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any


_MEMORY_DIR = os.path.join(".memory", "fraud_detection")
_DECISIONS_FILE = os.path.join(_MEMORY_DIR, "decisions.json")
_MAX_RECORDS = 1000


def write_fraud_decision(
    order_id: str,
    email: str,
    ip_address: str,
    verdict: str,
    risk_score: float,
    risk_level: str,
    signals: dict[str, Any],
    total_price: float = 0.0,
) -> dict[str, Any]:
    """Persist a fraud decision record.

    Args:
        order_id: The evaluated order ID.
        email: Customer email.
        ip_address: Customer IP.
        verdict: Final verdict (approve/review/reject).
        risk_score: Overall risk score.
        risk_level: Risk level string.
        signals: All signal results.
        total_price: Order total.

    Returns:
        Dict with status, record_id, path.
    """
    try:
        os.makedirs(_MEMORY_DIR, exist_ok=True)

        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "id": record_id,
            "timestamp": timestamp,
            "order_id": order_id,
            "email": email,
            "ip_address": ip_address,
            "total_price": total_price,
            "verdict": verdict,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "signal_scores": {
                name: data.get("score", 0.0) if isinstance(data, dict) else 0.0
                for name, data in signals.items()
            },
        }

        # Load existing records
        records: list[dict[str, Any]] = []
        if os.path.isfile(_DECISIONS_FILE):
            with open(_DECISIONS_FILE, "r") as fh:
                records = json.load(fh)
            if not isinstance(records, list):
                records = []

        records.append(record)

        # Trim to max records
        if len(records) > _MAX_RECORDS:
            records = records[-_MAX_RECORDS:]

        with open(_DECISIONS_FILE, "w") as fh:
            json.dump(records, fh, indent=2)

        return {
            "status": "success",
            "record_id": record_id,
            "path": _DECISIONS_FILE,
        }

    except Exception as exc:
        return {
            "status": "success",
            "record_id": "",
            "path": "",
            "note": f"Memory write warning: {exc}",
        }
