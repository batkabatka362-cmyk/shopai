"""ConfigManager — centralized configuration with runtime updates.

Loads YAML configs, supports runtime override, environment-specific settings.
Never deletes config — only adds/overrides.
"""
from __future__ import annotations

import copy
import os
import threading
from typing import Any

from utils.logger import get_logger

logger = get_logger("config.manager")

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


class ConfigManager:
    """Thread-safe centralized configuration."""

    _instance: ConfigManager | None = None
    _lock = threading.Lock()

    def __new__(cls) -> ConfigManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self) -> None:
        self._config: dict[str, Any] = {}
        self._overrides: dict[str, Any] = {}
        self._watchers: list[tuple[str, Any]] = []

    def load_yaml(self, path: str) -> dict[str, Any]:
        """Load a YAML config file and merge into config."""
        if not HAS_YAML:
            logger.warning("PyYAML not installed — skipping %s", path)
            return {}
        if not os.path.exists(path):
            return {}
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            with self._lock:
                self._deep_merge(self._config, data)
            logger.info("Loaded config: %s (%d keys)", path, len(data))
            return data
        except Exception as exc:
            logger.error("Failed to load %s: %s", path, exc)
            return {}

    def get(self, key: str, default: Any = None) -> Any:
        """Get config value. Overrides take precedence."""
        with self._lock:
            if key in self._overrides:
                return copy.deepcopy(self._overrides[key])
            return copy.deepcopy(self._config.get(key, default))

    def get_nested(self, *keys: str, default: Any = None) -> Any:
        """Get nested config: get_nested('engines', 'pricing', 'max_discount')."""
        with self._lock:
            current = {**self._config, **self._overrides}
            for key in keys:
                if isinstance(current, dict):
                    current = current.get(key)
                else:
                    return default
                if current is None:
                    return default
            return copy.deepcopy(current)

    def set(self, key: str, value: Any) -> None:
        """Set a runtime override (does not modify files)."""
        with self._lock:
            self._overrides[key] = copy.deepcopy(value)
        logger.info("Config override: %s = %s", key, str(value)[:50])

    def set_nested(self, *keys_and_value: Any) -> None:
        """Set nested config: set_nested('engines', 'pricing', 'max_discount', 50)."""
        *keys, value = keys_and_value
        with self._lock:
            current = self._overrides
            for key in keys[:-1]:
                current = current.setdefault(key, {})
            current[keys[-1]] = value

    def get_engine_config(self, engine_name: str) -> dict[str, Any]:
        """Get config for a specific engine."""
        return self.get_nested("engines", engine_name, default={})

    def snapshot(self) -> dict[str, Any]:
        """Get full config snapshot (merged)."""
        with self._lock:
            merged = copy.deepcopy(self._config)
            self._deep_merge(merged, self._overrides)
            return merged

    def reset_overrides(self) -> None:
        """Clear all runtime overrides."""
        with self._lock:
            self._overrides.clear()

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> None:
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ConfigManager._deep_merge(base[key], value)
            else:
                base[key] = value
