"""EngineConfig — per-engine configuration with defaults and overrides."""
from __future__ import annotations

import copy
from typing import Any

from .config_manager import ConfigManager


DEFAULTS = {
    "enabled": True,
    "timeout_seconds": 30,
    "retry_count": 1,
    "cache_ttl": 300,
    "max_input_size": 100000,
    "temperature": 0.7,
    "max_tokens": 2048,
}


class EngineConfig:
    """Configuration for a specific engine."""

    def __init__(self, engine_name: str) -> None:
        self._engine_name = engine_name
        self._cm = ConfigManager()

    def get(self, key: str, default: Any = None) -> Any:
        """Get engine-specific config with fallback to defaults."""
        engine_cfg = self._cm.get_engine_config(self._engine_name)
        if key in engine_cfg:
            return engine_cfg[key]
        global_default = DEFAULTS.get(key)
        return global_default if global_default is not None else default

    def is_enabled(self) -> bool:
        return bool(self.get("enabled", True))

    def timeout(self) -> int:
        return int(self.get("timeout_seconds", 30))

    def retry_count(self) -> int:
        return int(self.get("retry_count", 1))

    def cache_ttl(self) -> int:
        return int(self.get("cache_ttl", 300))

    def temperature(self) -> float:
        return float(self.get("temperature", 0.7))

    def max_tokens(self) -> int:
        return int(self.get("max_tokens", 2048))

    def to_dict(self) -> dict[str, Any]:
        engine_cfg = self._cm.get_engine_config(self._engine_name)
        merged = copy.deepcopy(DEFAULTS)
        merged.update(engine_cfg)
        merged["engine_name"] = self._engine_name
        return merged
