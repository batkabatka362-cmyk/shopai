"""AgentRegistry — maps agent names to class paths and capabilities."""

from __future__ import annotations

import threading
from datetime import datetime, timezone


class AgentRegistry:
    """Central registry of available agent types and their capabilities."""

    def __init__(self) -> None:
        self._registry: dict[str, dict] = {}
        # Lock guarding _registry mutations. Two startup paths
        # registering concurrently could otherwise race on the
        # duplicate-name check + dict write.
        self._lock = threading.Lock()

    def register(self, name: str, agent_class_path: str, capabilities: list[str]) -> None:
        """Register an agent type with its importable class path and capabilities."""
        with self._lock:
            if name in self._registry:
                raise ValueError(f"Agent type already registered: {name}")

            self._registry[name] = {
                "name": name,
                "class_path": agent_class_path,
                "capabilities": list(capabilities),
                "registered_at": datetime.now(timezone.utc).isoformat(),
            }

    def lookup(self, name: str) -> dict:
        """Look up a registered agent type by name."""
        with self._lock:
            if name not in self._registry:
                raise KeyError(f"Agent type not registered: {name}")
            return dict(self._registry[name])

    def lookup_by_capability(self, capability: str) -> list[dict]:
        """Return all registered agent types that have the given capability.

        Defensive `.get` so a future entry without a capabilities
        field can't crash the lookup with KeyError.
        """
        results = []
        with self._lock:
            for entry in self._registry.values():
                caps = entry.get("capabilities") or []
                if capability in caps:
                    results.append(dict(entry))
        return results

    def list_registered(self) -> list[dict]:
        """Return all registered agent types."""
        with self._lock:
            return [dict(entry) for entry in self._registry.values()]

    def unregister(self, name: str) -> bool:
        """Remove an agent type from the registry. Returns True if it existed."""
        with self._lock:
            if name not in self._registry:
                return False
            del self._registry[name]
            return True
