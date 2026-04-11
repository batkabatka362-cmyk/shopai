"""Bundle Engine — memory writer.

Persists bundle creation results to disk for future reference.
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


def write_bundle_result(
    bundles: list[dict[str, Any]],
    best_bundle: dict[str, Any] | None,
    cannibalization_risk: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write a bundle result record to memory.

    Args:
        bundles: List of bundle output dicts.
        best_bundle: Best bundle dict or None.
        cannibalization_risk: List of cannibalization result dicts.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        avg_savings = 0.0
        if bundles:
            avg_savings = round(
                sum(b.get("savings_pct", 0.0) for b in bundles) / len(bundles), 1,
            )

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "bundles_count": len(bundles),
            "avg_savings_pct": avg_savings,
            "best_bundle_products": (
                best_bundle.get("products", []) if best_bundle else []
            ),
            "cannibalization_flags": sum(
                1 for c in cannibalization_risk
                if c.get("cannibalization_risk", 0) > 0.5
            ),
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
