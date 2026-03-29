"""Metric collection and aggregation for monitoring dashboards."""

import time
from typing import Optional


class MetricCollector:
    """Collect, store, and aggregate metrics from various sources."""

    def __init__(self):
        self._storage: dict[str, list[dict]] = {}

    def collect(self, source: str, metric_name: str, value: float, tags: Optional[dict] = None) -> None:
        """Record a metric data point from a given source."""
        if metric_name not in self._storage:
            self._storage[metric_name] = []
        self._storage[metric_name].append({
            "value": float(value),
            "timestamp": time.time(),
            "source": source,
            "tags": tags or {},
        })

    def get_latest(self, metric_name: str) -> dict:
        """Get the most recent data point for a metric."""
        entries = self._storage.get(metric_name, [])
        if not entries:
            return {}
        return dict(entries[-1])

    def get_aggregated(self, metric_name: str, window_seconds: int = 300, agg: str = "avg") -> float:
        """Aggregate metric values within a time window.

        Args:
            metric_name: Metric to aggregate.
            window_seconds: Look-back window in seconds.
            agg: Aggregation function - avg, min, max, sum, count.
        """
        entries = self._storage.get(metric_name, [])
        cutoff = time.time() - window_seconds
        values = [e["value"] for e in entries if e["timestamp"] >= cutoff]
        if not values:
            return 0.0
        if agg == "avg":
            return sum(values) / len(values)
        if agg == "min":
            return min(values)
        if agg == "max":
            return max(values)
        if agg == "sum":
            return sum(values)
        if agg == "count":
            return float(len(values))
        return 0.0

    def list_metrics(self) -> list[str]:
        """List all known metric names."""
        return sorted(self._storage.keys())

    def get_dashboard_data(self, metric_names: list[str]) -> dict:
        """Get latest value and recent trend for each requested metric.

        Returns dict mapping metric_name to {latest, trend, count}.
        Trend is 'up', 'down', or 'stable' based on recent values.
        """
        result = {}
        for name in metric_names:
            entries = self._storage.get(name, [])
            if not entries:
                result[name] = {"latest": None, "trend": "unknown", "count": 0}
                continue

            latest = entries[-1]["value"]
            count = len(entries)

            # Determine trend from last 10 points
            recent = [e["value"] for e in entries[-10:]]
            if len(recent) < 2:
                trend = "stable"
            else:
                mid = len(recent) // 2
                first_half_avg = sum(recent[:mid]) / mid
                second_half_avg = sum(recent[mid:]) / (len(recent) - mid)
                diff = second_half_avg - first_half_avg
                threshold = abs(first_half_avg) * 0.05 if first_half_avg != 0 else 0.01
                if diff > threshold:
                    trend = "up"
                elif diff < -threshold:
                    trend = "down"
                else:
                    trend = "stable"

            result[name] = {"latest": latest, "trend": trend, "count": count}
        return result
