"""Demand Estimator — output formatting."""
from __future__ import annotations
import time
from typing import Any

def format_output(engine_name: str, results: dict[str, Any], data: dict[str, Any], elapsed: float) -> dict[str, Any]:
    vol = results.get("volume_projection", {}).get("data") or {}
    trend = results.get("demand_trend", {}).get("data") or {}
    monthly = vol.get("expected_monthly_units", 0)
    direction = trend.get("trend_direction", "unknown")
    summary = f"Demand estimate: {monthly} units/month ({direction} trend). Category: {data.get('category', '?')}."
    return {
        "status": "success",
        "data": {"summary": summary, "estimated_monthly_units": monthly, "trend_direction": direction, **{k: v for k, v in results.items()}},
        "meta": {"engine": engine_name, "confidence": 0.70, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
        "error": None,
    }
