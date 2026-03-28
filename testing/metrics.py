"""Metrics — performance metrics collection."""
from __future__ import annotations
from typing import Any
from utils.helpers import timestamp_now
from utils.logger import get_logger

logger = get_logger("testing.metrics")


class MetricsCollector:
    def __init__(self) -> None:
        self._metrics: list[dict[str, Any]] = []

    def record(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        self._metrics.append({"name": name, "value": value, "tags": tags or {}, "timestamp": timestamp_now()})

    def get(self, name: str) -> list[dict[str, Any]]:
        return [m for m in self._metrics if m["name"] == name]

    def summary(self) -> dict[str, Any]:
        names = set(m["name"] for m in self._metrics)
        return {name: len(self.get(name)) for name in names}
