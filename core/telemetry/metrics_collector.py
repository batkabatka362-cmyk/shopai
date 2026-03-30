"""MetricsCollector — collects and aggregates system metrics."""
from __future__ import annotations

import threading
import time
from typing import Any


class MetricsCollector:
    """Thread-safe metrics collection with aggregation."""

    _instance: MetricsCollector | None = None
    _lock_cls = threading.Lock()

    def __new__(cls) -> MetricsCollector:
        with cls._lock_cls:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self) -> None:
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def histogram(self, name: str, value: float) -> None:
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value)
            if len(self._histograms[name]) > 10000:
                self._histograms[name] = self._histograms[name][-10000:]

    def get_counter(self, name: str) -> int:
        with self._lock:
            return self._counters.get(name, 0)

    def get_gauge(self, name: str) -> float:
        with self._lock:
            return self._gauges.get(name, 0.0)

    def get_histogram_stats(self, name: str) -> dict[str, float]:
        with self._lock:
            values = list(self._histograms.get(name, []))
        if not values:
            return {"count": 0}
        values.sort()
        n = len(values)
        return {
            "count": n,
            "min": round(values[0], 4),
            "max": round(values[-1], 4),
            "avg": round(sum(values) / n, 4),
            "p50": round(values[n // 2], 4),
            "p95": round(values[int(n * 0.95)], 4),
            "p99": round(values[int(n * 0.99)], 4),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {k: self.get_histogram_stats(k) for k in self._histograms},
            }

    def clear(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
