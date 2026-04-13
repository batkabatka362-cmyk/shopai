"""StatsProvider protocol + StatsRegistry — standardised stats collection.

53 modules across ``core/`` expose a ``get_stats() -> dict`` method.
Before this module they were all independent — there was no way to
collect a system-wide snapshot, no standard envelope (timestamp,
component name), and no protection against one broken ``get_stats()``
crashing a dashboard sweep.

This module provides:

* :class:`StatsProvider` — ``runtime_checkable`` Protocol so any
  object with ``get_stats() -> dict[str, Any]`` satisfies it.
* :class:`StatsRegistry` — singleton registry. Modules register
  themselves (or are discovered lazily). The registry can then
  collect stats from all registered providers in one call.
* :func:`stats_envelope` — wraps a raw stats dict in a standard
  envelope with ``component``, ``timestamp``, and ``stats`` keys.
* :func:`get_stats_registry` — DCLP singleton accessor.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Protocol, runtime_checkable

from utils.logger import get_logger

logger = get_logger("telemetry.stats")


# ═══════════════════════════════════════════════
# PROTOCOL
# ═══════════════════════════════════════════════

@runtime_checkable
class StatsProvider(Protocol):
    """Any object that exposes ``get_stats() -> dict[str, Any]``."""

    def get_stats(self) -> dict[str, Any]: ...


# ═══════════════════════════════════════════════
# ENVELOPE HELPER
# ═══════════════════════════════════════════════

def stats_envelope(component: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Wrap *raw* stats in a standard envelope.

    Returns::

        {
            "component": "brain.strategy_planner",
            "timestamp": 1712929200.0,
            "stats": { ... raw dict ... },
        }
    """
    return {
        "component": component,
        "timestamp": time.time(),
        "stats": raw,
    }


# ═══════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════

# Known getter functions for lazy discovery.
# Maps component name → (module_path, getter_function_name).
# Adding entries here is enough — the registry will import and
# call them on first ``discover()``.
_KNOWN_PROVIDERS: dict[str, tuple[str, str]] = {
    "production.audit":       ("core.system.production",          "get_audit"),
    "brain.strategy_planner": ("core.brain.strategy_planner",     "get_strategy_planner"),
    "brain.revenue_strategy": ("core.brain.revenue_strategy",     "get_revenue_strategy"),
    "ai.product_finder":      ("core.ai.product_finder",          "get_product_finder"),
    "memory.unified":         ("core.memory.unified_memory",      "get_unified_memory"),
    "system.health_monitor":  ("core.system.health_monitor",      "get_health_monitor"),
    "system.notifications":   ("core.system.notifications",       "get_notifications"),
    "system.alerts":          ("core.system.alerts",              "get_alert_system"),
}


class StatsRegistry:
    """Central registry for :class:`StatsProvider` instances.

    Modules either self-register via :meth:`register` or are
    discovered lazily via :meth:`discover` which walks
    ``_KNOWN_PROVIDERS``.
    """

    def __init__(self) -> None:
        self._providers: dict[str, StatsProvider] = {}
        self._lock = threading.Lock()
        self._discovered = False

    # ── mutation ──────────────────────────────────────────────

    def register(self, name: str, provider: StatsProvider) -> None:
        """Register a stats provider under *name*."""
        with self._lock:
            self._providers[name] = provider

    def unregister(self, name: str) -> None:
        """Remove provider *name* (no-op if absent)."""
        with self._lock:
            self._providers.pop(name, None)

    def discover(self) -> int:
        """Lazily import and register all known providers.

        Returns the number of providers successfully registered.
        Safe to call multiple times — already-registered names
        are skipped, and import failures are logged but ignored.
        """
        registered = 0
        for name, (mod_path, getter_name) in _KNOWN_PROVIDERS.items():
            if name in self._providers:
                continue
            try:
                import importlib
                mod = importlib.import_module(mod_path)
                getter = getattr(mod, getter_name)
                obj = getter()
                if isinstance(obj, StatsProvider):
                    self.register(name, obj)
                    registered += 1
                else:
                    logger.debug("discover: %s.%s() does not satisfy StatsProvider",
                                 mod_path, getter_name)
            except Exception as exc:
                logger.debug("discover: failed to load %s: %s", name, exc)
        self._discovered = True
        return registered

    # ── collection ───────────────────────────────────────────

    def collect_all(self, *, auto_discover: bool = True) -> dict[str, Any]:
        """Collect stats from every registered provider.

        Returns a system-wide snapshot::

            {
                "timestamp": 1712929200.0,
                "components": {
                    "brain.strategy_planner": { ... },
                    ...
                },
                "component_count": 13,
                "collection_errors": [],
            }
        """
        if auto_discover and not self._discovered:
            self.discover()

        with self._lock:
            providers = dict(self._providers)

        results: dict[str, dict[str, Any]] = {}
        errors: list[dict[str, str]] = []

        for name, provider in sorted(providers.items()):
            try:
                results[name] = provider.get_stats()
            except Exception as exc:
                errors.append({"component": name, "error": str(exc)[:200]})

        return {
            "timestamp": time.time(),
            "components": results,
            "component_count": len(results),
            "collection_errors": errors,
        }

    def collect(self, name: str) -> dict[str, Any] | None:
        """Collect stats from a single named provider."""
        with self._lock:
            provider = self._providers.get(name)
        if provider is None:
            return None
        return stats_envelope(name, provider.get_stats())

    # ── introspection ────────────────────────────────────────

    def list_providers(self) -> list[str]:
        """Return sorted list of registered provider names."""
        with self._lock:
            return sorted(self._providers.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._providers)


# ═══════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════

_registry: StatsRegistry | None = None
_registry_lock = threading.Lock()


def get_stats_registry() -> StatsRegistry:
    """Return the singleton :class:`StatsRegistry`."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = StatsRegistry()
    return _registry
