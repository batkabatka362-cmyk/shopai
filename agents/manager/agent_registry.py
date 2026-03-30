"""AgentRegistry — maps agent names to class paths and capabilities."""

from __future__ import annotations

from datetime import datetime, timezone


class AgentRegistry:
    """Central registry of available agent types and their capabilities."""

    def __init__(self) -> None:
        self._registry: dict[str, dict] = {}

    def register(self, name: str, agent_class_path: str, capabilities: list[str]) -> None:
        """Register an agent type with its importable class path and capabilities."""
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
        if name not in self._registry:
            raise KeyError(f"Agent type not registered: {name}")
        return dict(self._registry[name])

    def lookup_by_capability(self, capability: str) -> list[dict]:
        """Return all registered agent types that have the given capability."""
        results = []
        for entry in self._registry.values():
            if capability in entry["capabilities"]:
                results.append(dict(entry))
        return results

    def list_registered(self) -> list[dict]:
        """Return all registered agent types."""
        return [dict(entry) for entry in self._registry.values()]

    def unregister(self, name: str) -> bool:
        """Remove an agent type from the registry. Returns True if it existed."""
        if name not in self._registry:
            return False
        del self._registry[name]
        return True
