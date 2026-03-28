from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from .memory_manager import MemoryManager

logger = get_logger("memory.router")


class MemoryRouter:
    """Routes memory operations to the appropriate store based on data type and retention policy."""

    SHORT_TERM_TYPES = {"task_result", "intermediate", "cache", "temp"}
    LONG_TERM_TYPES = {"learned", "pattern", "strategy", "config", "history"}

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._manager = memory_manager

    def route_store(self, key: str, value: Any, data_type: str = "temp") -> str:
        if data_type in self.LONG_TERM_TYPES:
            self._manager.store_long_term(key, value, tags=[data_type])
            destination = "long_term"
        else:
            self._manager.store_short_term(key, value)
            destination = "short_term"
        logger.info("Routed '%s' (type=%s) -> %s", key, data_type, destination)
        return destination

    def route_recall(self, key: str) -> Any | None:
        return self._manager.recall(key)

    def route_recall_by_type(self, data_type: str) -> list[tuple[str, Any]]:
        return self._manager.recall_by_tag(data_type)
