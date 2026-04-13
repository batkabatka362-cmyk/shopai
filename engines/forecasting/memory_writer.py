"""Forecasting Engine — memory writer.

Persists forecast results to disk for future accuracy tracking
and model improvement feedback loops.

1 file = 1 job: write forecast records only.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_forecast(
    metric: str,
    forecast_periods: int,
    granularity: str,
    model_accuracy: dict[str, Any],
    overall_confidence: float,
    trend_direction: str,
    seasonality_detected: bool,
    forecast_count: int,
) -> dict[str, Any]:
    """Write a forecast record to memory.

    Args:
        metric: The metric that was forecast (e.g. "daily_revenue").
        forecast_periods: Number of periods forecast.
        granularity: Time granularity.
        model_accuracy: MAE/RMSE/MAPE/R-squared dict.
        overall_confidence: Composite confidence score.
        trend_direction: Detected trend direction.
        seasonality_detected: Whether seasonality was found.
        forecast_count: Number of forecast points generated.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "metric": str(metric),
            "forecast_periods": int(forecast_periods),
            "granularity": str(granularity),
            "model_accuracy": model_accuracy,
            "overall_confidence": round(float(overall_confidence), 4),
            "trend_direction": str(trend_direction),
            "seasonality_detected": bool(seasonality_detected),
            "forecast_count": int(forecast_count),
            "outcome_actual": None,  # To be filled when actuals arrive
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
