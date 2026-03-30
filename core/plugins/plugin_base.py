"""PluginBase — abstract base for all plugins."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class PluginBase(ABC):
    """Base class for ShopAI plugins.

    Plugins can:
      - Register custom engines
      - Add custom step executors
      - Add custom validators
      - Subscribe to events
      - Add API endpoints

    Plugins CANNOT:
      - Modify existing engine code
      - Delete files or system structure
      - Override core system behavior
    """

    plugin_name: str = "base"
    plugin_version: str = "1.0.0"
    plugin_description: str = ""

    @abstractmethod
    def initialize(self, context: dict[str, Any]) -> None:
        """Initialize plugin with system context."""

    @abstractmethod
    def register(self) -> dict[str, Any]:
        """Register plugin capabilities. Returns manifest."""

    def shutdown(self) -> None:
        """Clean up plugin resources."""

    def health_check(self) -> dict[str, Any]:
        """Check plugin health."""
        return {"plugin": self.plugin_name, "status": "ok", "version": self.plugin_version}
