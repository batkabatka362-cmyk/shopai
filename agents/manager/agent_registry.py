"""Agent Registry — register and lookup agent types."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("agents.registry")


class AgentRegistry:
    def __init__(self) -> None:
        self._registry: dict[str, dict[str, Any]] = {}

    def register(self, role: str, capabilities: list[str], config: dict[str, Any] | None = None) -> None:
        self._registry[role] = {"capabilities": capabilities, "config": config or {}}
        logger.info("Registered agent role: %s", role)

    def get(self, role: str) -> dict[str, Any] | None:
        return self._registry.get(role)

    def find_by_capability(self, capability: str) -> list[str]:
        return [role for role, info in self._registry.items() if capability in info["capabilities"]]

    def list_roles(self) -> list[str]:
        return list(self._registry.keys())
