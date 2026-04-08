"""AnomalyDetector — detects anomalies in system metrics.

READ-ONLY: monitors metrics, detects deviations, never modifies code.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from utils.helpers import safe_float
from utils.logger import get_logger

logger = get_logger("monitor.anomaly")


class AnomalyDetector:
    """Detects anomalies in system metrics using statistical methods."""

    def __init__(self, sensitivity: float = 2.0) -> None:
        self._sensitivity = safe_float(sensitivity, default=2.0) or 2.0
        self._baselines: dict[str, dict[str, float]] = {}
        # Protect ``_baselines`` from concurrent update/read.
        # Audit pass 51.
        self._lock = threading.Lock()

    def update_baseline(self, metric_name: str, values: list[float]) -> None:
        """Update baseline stats for a metric.

        Pre-audit crashed on None values / non-list input / lists
        containing non-numerics. Now coerces each value via
        safe_float and drops unparseable entries. Audit pass 51.
        """
        if not isinstance(metric_name, str) or not metric_name:
            return
        if not isinstance(values, (list, tuple)) or not values:
            return
        clean = [safe_float(v) for v in values]
        if not clean:
            return
        n = len(clean)
        mean = sum(clean) / n
        variance = sum((v - mean) ** 2 for v in clean) / n
        std = variance ** 0.5
        entry = {
            "mean": mean,
            "std": std,
            "min": min(clean),
            "max": max(clean),
            "count": n,
            "updated_at": time.time(),
        }
        with self._lock:
            self._baselines[metric_name] = entry

    def check(self, metric_name: str, value: float) -> dict[str, Any]:
        """Check if a value is anomalous compared to baseline."""
        if not isinstance(metric_name, str):
            return {"metric": metric_name, "anomaly": False, "reason": "bad_metric_name"}
        with self._lock:
            baseline = self._baselines.get(metric_name)
        if baseline is None:
            return {"metric": metric_name, "anomaly": False, "reason": "no_baseline"}

        # Defensive: value can arrive as a string / None from
        # upstream metric collectors. Audit pass 51.
        value = safe_float(value)
        mean = baseline["mean"]
        std = baseline["std"]

        if std == 0:
            is_anomaly = value != mean
        else:
            z_score = abs(value - mean) / std
            is_anomaly = z_score > self._sensitivity

        result = {
            "metric": metric_name,
            "value": value,
            "anomaly": is_anomaly,
            "baseline_mean": round(mean, 4),
            "baseline_std": round(std, 4),
            "deviation": round(abs(value - mean) / std, 2) if std > 0 else 0,
            "direction": "high" if value > mean else "low" if value < mean else "normal",
        }

        if is_anomaly:
            logger.warning("Anomaly detected: %s=%.4f (baseline=%.4f±%.4f)",
                           metric_name, value, mean, std)

        return result

    def check_batch(self, metrics: dict[str, float]) -> list[dict[str, Any]]:
        """Check multiple metrics at once. Returns only anomalies."""
        if not isinstance(metrics, dict):
            return []
        results = []
        for name, value in metrics.items():
            result = self.check(name, value)
            if result.get("anomaly"):
                results.append(result)
        return results

    def get_baselines(self) -> dict[str, dict[str, float]]:
        """Get all current baselines as a deep-ish copy.

        Pre-audit ``dict(self._baselines)`` produced a shallow
        copy — caller mutating the inner dicts affected the
        stored state. Audit pass 51.
        """
        with self._lock:
            return {k: dict(v) for k, v in self._baselines.items()}
