"""Strategy Store — reusable business strategies."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("knowledge.strategies")


class StrategyStore:
    def __init__(self) -> None:
        self._strategies: dict[str, dict[str, Any]] = {}

    def save(self, name: str, strategy: dict[str, Any]) -> None:
        self._strategies[name] = strategy
        logger.info("Saved strategy: %s", name)

    def load(self, name: str) -> dict[str, Any] | None:
        return self._strategies.get(name)

    def list_strategies(self) -> list[str]:
        return list(self._strategies.keys())
