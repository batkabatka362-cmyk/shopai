"""Log Manager — centralized log management."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("monitoring.logs")


class LogManager:
    def __init__(self) -> None:
        self._logs: list[dict[str, Any]] = []

    def log(self, level: str, source: str, message: str, data: dict[str, Any] | None = None) -> None:
        from utils.helpers import timestamp_now
        self._logs.append({"level": level, "source": source, "message": message, "data": data, "timestamp": timestamp_now()})

    def query(self, level: str | None = None, source: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        results = self._logs
        if level:
            results = [l for l in results if l["level"] == level]
        if source:
            results = [l for l in results if l["source"] == source]
        return results[-limit:]

    def clear(self) -> int:
        count = len(self._logs)
        self._logs.clear()
        return count
