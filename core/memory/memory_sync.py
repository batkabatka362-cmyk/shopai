from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from .memory_manager import MemoryManager

logger = get_logger("memory.sync")


class MemorySync:
    """Synchronizes memory between short-term and long-term stores, and handles promotion."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._manager = memory_manager
        self._promotion_rules: list[dict[str, Any]] = []

    def add_promotion_rule(self, key_pattern: str, target_tags: list[str] | None = None) -> None:
        self._promotion_rules.append({
            "key_pattern": key_pattern,
            "target_tags": target_tags or ["promoted"],
        })

    def promote(self, key: str, tags: list[str] | None = None) -> bool:
        value = self._manager.recall(key)
        if value is None:
            logger.warning("Cannot promote key '%s': not found", key)
            return False
        self._manager.store_long_term(key, value, tags=tags or ["promoted"])
        self._manager.forget_short_term(key)
        logger.info("Promoted '%s' from short-term to long-term", key)
        return True

    def demote(self, key: str) -> bool:
        value = self._manager.recall(key)
        if value is None:
            logger.warning("Cannot demote key '%s': not found", key)
            return False
        self._manager.store_short_term(key, value)
        self._manager.forget_long_term(key)
        logger.info("Demoted '%s' from long-term to short-term", key)
        return True

    def sync_stats(self) -> dict[str, Any]:
        return {
            **self._manager.get_stats(),
            "promotion_rules": len(self._promotion_rules),
        }
