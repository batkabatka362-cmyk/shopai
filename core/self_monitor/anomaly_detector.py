"""AnomalyDetector — detects anomalies in system metrics.

READ-ONLY: monitors metrics, detects deviations, never modifies code.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("monitor.anomaly")


class AnomalyDetector:
    """Detects anomalies in system metrics using statistical methods."""

    def __init__(self, sensitivity: float = 2.0) -> None:
        self._sensitivity = sensitivity  # standard deviations for threshold
        self._baselines: dict[str, dict[str, float]] = {}

    def update_baseline(self, metric_name: str, values: list[float]) -> None:
        """Update baseline stats for a metric."""
        if not values:
            return
        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        std = variance ** 0.5
        self._baselines[metric_name] = {
            "mean": mean,
            "std": std,
            "min": min(values),
            "max": max(values),
            "count": n,
            "updated_at": time.time(),
        }

    def check(self, metric_name: str, value: float) -> dict[str, Any]:
        """Check if a value is anomalous compared to baseline."""
        if metric_name not in self._baselines:
            return {"metric": metric_name, "anomaly": False, "reason": "no_baseline"}

        baseline = self._baselines[metric_name]
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
        results = []
        for name, value in metrics.items():
            result = self.check(name, value)
            if result["anomaly"]:
                results.append(result)
        return results

    def get_baselines(self) -> dict[str, dict[str, float]]:
        """Get all current baselines."""
        return dict(self._baselines)
