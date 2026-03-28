"""Metric Collector — collects system metrics."""
from __future__ import annotations
from typing import Any
from utils.helpers import timestamp_now
from utils.logger import get_logger

logger = get_logger("monitoring.metrics")


class MetricCollector:
    def __init__(self) -> None:
        self._metrics: dict[str, list[dict[str, Any]]] = {}

    def collect(self, name: str, value: float) -> None:
        if name not in self._metrics:
            self._metrics[name] = []
        self._metrics[name].append({"value": value, "timestamp": timestamp_now()})

    def get_latest(self, name: str) -> float | None:
        entries = self._metrics.get(name, [])
        return entries[-1]["value"] if entries else None

    def get_all(self, name: str) -> list[dict[str, Any]]:
        return self._metrics.get(name, [])

    def list_metrics(self) -> list[str]:
        return list(self._metrics.keys())
