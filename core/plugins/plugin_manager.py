"""PluginManager — high-level plugin lifecycle management."""
from __future__ import annotations

import importlib
from typing import Any

from utils.logger import get_logger
from .plugin_base import PluginBase
from .plugin_registry import PluginRegistry

logger = get_logger("plugins.manager")


class PluginManager:
    """Manages plugin lifecycle: discover, load, register, monitor."""

    def __init__(self) -> None:
        self._registry = PluginRegistry()

    @property
    def registry(self) -> PluginRegistry:
        return self._registry

    def load_plugin(self, module_path: str, class_name: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Load a plugin by module path and class name."""
        try:
            module = importlib.import_module(module_path)
            plugin_class = getattr(module, class_name)
            if not issubclass(plugin_class, PluginBase):
                return {"status": "error", "error": f"{class_name} is not a PluginBase subclass"}
            plugin = plugin_class()
            return self._registry.register(plugin, context)
        except (ImportError, AttributeError) as exc:
            logger.error("Failed to load plugin %s.%s: %s", module_path, class_name, exc)
            return {"status": "error", "error": str(exc)}

    def register_plugin(self, plugin: PluginBase, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Register an already-instantiated plugin."""
        return self._registry.register(plugin, context)

    def unload_plugin(self, plugin_name: str) -> bool:
        return self._registry.unregister(plugin_name)

    def list_plugins(self) -> list[dict[str, Any]]:
        return self._registry.list_plugins()

    def health_check(self) -> dict[str, Any]:
        return self._registry.health_check()

    def get_plugin(self, name: str) -> PluginBase | None:
        return self._registry.get(name)
