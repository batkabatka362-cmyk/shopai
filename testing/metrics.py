"""Performance metrics tracking and aggregation."""

import time
import math
from typing import Any, Optional


class PerformanceMetrics:
    """Track, aggregate, and compare performance metrics."""

    # Well-known metric names
    LATENCY = "latency"
    THROUGHPUT = "throughput"
    ERROR_RATE = "error_rate"
    TOKEN_USAGE = "token_usage"

    def __init__(self):
        self._metrics: dict[str, list[dict]] = {}

    def record(self, metric_name: str, value: float, tags: Optional[dict] = None) -> None:
        """Record a metric data point."""
        if metric_name not in self._metrics:
            self._metrics[metric_name] = []
        self._metrics[metric_name].append({
            "value": float(value),
            "timestamp": time.time(),
            "tags": tags or {},
        })

    def get(self, metric_name: str, aggregation: str = "avg") -> float:
        """Get an aggregated value for a metric.

        Supported aggregations: avg, min, max, sum, count, p95, p99.
        """
        entries = self._metrics.get(metric_name, [])
        if not entries:
            return 0.0

        values = [e["value"] for e in entries]
        return self._aggregate(values, aggregation)

    def _aggregate(self, values: list[float], aggregation: str) -> float:
        if not values:
            return 0.0
        if aggregation == "avg":
            return sum(values) / len(values)
        if aggregation == "min":
            return min(values)
        if aggregation == "max":
            return max(values)
        if aggregation == "sum":
            return sum(values)
        if aggregation == "count":
            return float(len(values))
        if aggregation in ("p95", "p99"):
            return self._percentile(values, 95 if aggregation == "p95" else 99)
        return 0.0

    @staticmethod
    def _percentile(values: list[float], pct: int) -> float:
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        if n == 1:
            return sorted_vals[0]
        rank = (pct / 100.0) * (n - 1)
        low = int(math.floor(rank))
        high = min(low + 1, n - 1)
        frac = rank - low
        return sorted_vals[low] + frac * (sorted_vals[high] - sorted_vals[low])

    def get_timeseries(self, metric_name: str, window: int = 100) -> list[dict]:
        """Get the last `window` data points for a metric as a timeseries."""
        entries = self._metrics.get(metric_name, [])
        recent = entries[-window:]
        return [{"value": e["value"], "timestamp": e["timestamp"], "tags": e["tags"]} for e in recent]

    def compare(self, baseline: dict, current: dict) -> dict:
        """Compare baseline vs current metrics, returning % change per metric."""
        result = {}
        all_keys = set(baseline.keys()) | set(current.keys())
        for key in sorted(all_keys):
            b = baseline.get(key, 0.0)
            c = current.get(key, 0.0)
            if b == 0:
                pct_change = 0.0 if c == 0 else float("inf")
            else:
                pct_change = round(((c - b) / abs(b)) * 100, 4)
            result[key] = {
                "baseline": b,
                "current": c,
                "pct_change": pct_change,
                "improved": pct_change < 0 if key in ("latency", "error_rate") else pct_change > 0,
            }
        return result

    def reset(self, metric_name: Optional[str] = None) -> None:
        """Reset a specific metric or all metrics if no name given."""
        if metric_name is None:
            self._metrics.clear()
        else:
            self._metrics.pop(metric_name, None)

    def get_summary(self) -> dict:
        """Get a summary of all tracked metrics."""
        summary = {}
        for name, entries in self._metrics.items():
            values = [e["value"] for e in entries]
            summary[name] = {
                "count": len(values),
                "avg": round(sum(values) / len(values), 4) if values else 0.0,
                "min": min(values) if values else 0.0,
                "max": max(values) if values else 0.0,
                "sum": round(sum(values), 4),
                "latest": values[-1] if values else None,
            }
        return summary
