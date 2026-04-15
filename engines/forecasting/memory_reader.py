"""Forecasting Engine — memory reader.

Reads past forecast records from memory storage for accuracy tracking
and model quality feedback.

1 file = 1 job: read forecast history only.
"""
from __future__ import annotations

import copy
import json
import os
import time
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_recent_forecasts(
    metric: str | None = None,
    hours: float = 168.0,
    limit: int = 50,
) -> dict[str, Any]:
    """Read recent forecast records, optionally filtered by metric.

    Args:
        metric: Optional metric name to filter by.
        hours: Time window in hours (default 168 = 7 days).
        limit: Max records to return.

    Returns:
        Structured dict with recent forecast records.
    """
    try:
        records = _load_records()

        # Filter by time window
        cutoff = time.time() - (hours * 3600)
        recent: list[dict[str, Any]] = []
        for rec in records:
            ts_str = rec.get("timestamp", "")
            try:
                rec_time = time.mktime(time.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ"))
                if rec_time >= cutoff:
                    recent.append(rec)
            except (ValueError, OverflowError):
                continue

        # Filter by metric if specified
        if metric is not None:
            recent = [r for r in recent if r.get("metric") == metric]

        # Sort by timestamp descending, limit
        recent = sorted(
            recent,
            key=lambda r: r.get("timestamp", ""),
            reverse=True,
        )[:limit]

        # Compute average past accuracy if records exist
        avg_accuracy = _average_accuracy(recent)

        return {
            "status": "success",
            "records": copy.deepcopy(recent),
            "count": len(recent),
            "avg_accuracy": avg_accuracy,
        }
    except Exception as exc:
        return {
            "status": "success",
            "records": [],
            "count": 0,
            "avg_accuracy": None,
            "note": f"Memory read warning: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_records(max_files: int | None = None) -> list[dict[str, Any]]:
    """Load records from the memory directory.

    Delegates to :func:`engines._memory_base.load_recent_records` so
    every engine shares one optimised scandir walk instead of keeping
    a near-identical O(N) copy. ``max_files`` caps the read to the
    most-recently-modified N files — unset means "read everything".
    """
    from engines._memory_base import load_recent_records
    return load_recent_records(_MEMORY_DIR, max_files=max_files)


def _average_accuracy(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Compute average accuracy metrics across recent forecast records."""
    if not records:
        return None

    mae_vals: list[float] = []
    rmse_vals: list[float] = []
    mape_vals: list[float] = []
    r2_vals: list[float] = []

    for rec in records:
        acc = rec.get("model_accuracy", {})
        if not isinstance(acc, dict):
            continue
        if "mae" in acc:
            mae_vals.append(float(acc["mae"]))
        if "rmse" in acc:
            rmse_vals.append(float(acc["rmse"]))
        if "mape" in acc:
            mape_vals.append(float(acc["mape"]))
        if "r_squared" in acc:
            r2_vals.append(float(acc["r_squared"]))

    if not mae_vals:
        return None

    return {
        "avg_mae": round(sum(mae_vals) / len(mae_vals), 4) if mae_vals else 0.0,
        "avg_rmse": round(sum(rmse_vals) / len(rmse_vals), 4) if rmse_vals else 0.0,
        "avg_mape": round(sum(mape_vals) / len(mape_vals), 2) if mape_vals else 0.0,
        "avg_r_squared": round(sum(r2_vals) / len(r2_vals), 4) if r2_vals else 0.0,
        "sample_count": len(records),
    }
