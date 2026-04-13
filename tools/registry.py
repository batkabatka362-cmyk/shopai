"""ToolRegistry — singleton catalogue of all registered tool adapters.

Provides lookup by name, capability (action), and category, plus a
bulk health-check that probes every registered adapter.
"""
from __future__ import annotations

import threading
from typing import Any

from .base import BaseToolAdapter, HealthStatus


class ToolRegistry:
    """Singleton registry of :class:`BaseToolAdapter` instances.

    Thread-safe.  Use :pymeth:`instance` to get the shared singleton or
    instantiate directly for testing.
    """

    _singleton: ToolRegistry | None = None
    _singleton_lock = threading.Lock()

    @classmethod
    def instance(cls) -> ToolRegistry:
        """Return (or create) the process-wide singleton."""
        if cls._singleton is None:
            with cls._singleton_lock:
                if cls._singleton is None:
                    cls._singleton = cls()
        return cls._singleton

    @classmethod
    def reset_singleton(cls) -> None:
        """Discard the singleton (useful in tests)."""
        with cls._singleton_lock:
            cls._singleton = None

    def __init__(self) -> None:
        self._adapters: dict[str, BaseToolAdapter] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, adapter: BaseToolAdapter) -> None:
        """Register an adapter.  Replaces any existing adapter with the same name."""
        if not adapter.tool_name:
            raise ValueError("Adapter must have a non-empty tool_name")
        with self._lock:
            self._adapters[adapter.tool_name] = adapter

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get(self, tool_name: str) -> BaseToolAdapter | None:
        """Return the adapter registered under *tool_name*, or ``None``."""
        with self._lock:
            return self._adapters.get(tool_name)

    def find_by_capability(self, action: str) -> list[BaseToolAdapter]:
        """Return all adapters whose :pymeth:`capabilities` include *action*."""
        with self._lock:
            adapters = list(self._adapters.values())
        return [a for a in adapters if action in a.capabilities()]

    def find_by_category(self, category: str) -> list[BaseToolAdapter]:
        """Return all adapters belonging to *category*."""
        with self._lock:
            return [a for a in self._adapters.values() if a.tool_category == category]

    def list_all(self) -> list[dict[str, Any]]:
        """Return summary dicts for every registered adapter."""
        with self._lock:
            adapters = list(self._adapters.values())
        result = []
        for adapter in adapters:
            result.append({
                "tool_name": adapter.tool_name,
                "tool_category": adapter.tool_category,
                "version": adapter.version,
                "capabilities": adapter.capabilities(),
            })
        return result

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_check_all(self) -> dict[str, HealthStatus]:
        """Probe every adapter and return a mapping of name -> status."""
        with self._lock:
            adapters = dict(self._adapters)
        results: dict[str, HealthStatus] = {}
        for name, adapter in adapters.items():
            try:
                results[name] = adapter.health_check()
            except Exception as exc:
                results[name] = HealthStatus(healthy=False, error=str(exc))
        return results

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        with self._lock:
            return len(self._adapters)

    def __contains__(self, tool_name: str) -> bool:
        with self._lock:
            return tool_name in self._adapters
