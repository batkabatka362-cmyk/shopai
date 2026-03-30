"""PluginRegistry — manages registered plugins."""
from __future__ import annotations

import threading
from typing import Any

from utils.logger import get_logger
from .plugin_base import PluginBase

logger = get_logger("plugins.registry")


class PluginRegistry:
    """Thread-safe plugin registry."""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginBase] = {}
        self._manifests: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def register(self, plugin: PluginBase, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Register and initialize a plugin."""
        name = plugin.plugin_name
        with self._lock:
            if name in self._plugins:
                return {"status": "already_registered", "plugin": name}

        try:
            plugin.initialize(context or {})
            manifest = plugin.register()
        except Exception as exc:
            logger.error("Plugin '%s' failed to initialize: %s", name, exc)
            return {"status": "failed", "plugin": name, "error": str(exc)}

        with self._lock:
            self._plugins[name] = plugin
            self._manifests[name] = manifest

        logger.info("Plugin registered: %s v%s", name, plugin.plugin_version)
        return {"status": "registered", "plugin": name, "manifest": manifest}

    def unregister(self, plugin_name: str) -> bool:
        with self._lock:
            plugin = self._plugins.pop(plugin_name, None)
            self._manifests.pop(plugin_name, None)
        if plugin:
            try:
                plugin.shutdown()
            except Exception:
                pass
            return True
        return False

    def get(self, plugin_name: str) -> PluginBase | None:
        with self._lock:
            return self._plugins.get(plugin_name)

    def list_plugins(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"name": p.plugin_name, "version": p.plugin_version, "description": p.plugin_description}
                for p in self._plugins.values()
            ]

    def health_check(self) -> dict[str, Any]:
        results = {}
        with self._lock:
            plugins = list(self._plugins.items())
        for name, plugin in plugins:
            try:
                results[name] = plugin.health_check()
            except Exception as exc:
                results[name] = {"plugin": name, "status": "error", "error": str(exc)}
        return results
