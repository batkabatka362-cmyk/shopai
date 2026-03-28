from __future__ import annotations

import threading
from typing import Any

from utils.logger import get_logger

logger = get_logger("state.global")


class GlobalState:
    """Singleton global state shared across the entire system."""

    _instance: GlobalState | None = None
    _lock = threading.Lock()

    def __new__(cls) -> GlobalState:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._data: dict[str, Any] = {}
                cls._instance._initialized = False
        return cls._instance

    def initialize(self, config: dict[str, Any] | None = None) -> None:
        with self._lock:
            if self._initialized:
                logger.warning("Global state already initialized, re-initializing")
            self._data = {
                "system_status": "initializing",
                "active_engines": [],
                "active_sessions": {},
                "config": config or {},
            }
            self._initialized = True
            logger.info("Global state initialized")

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value

    def update(self, updates: dict[str, Any]) -> None:
        with self._lock:
            self._data.update(updates)

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def system_status(self) -> str:
        return self._data.get("system_status", "unknown")

    @system_status.setter
    def system_status(self, status: str) -> None:
        self.set("system_status", status)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def reset(self) -> None:
        with self._lock:
            self._data.clear()
            self._initialized = False
        logger.info("Global state reset")
