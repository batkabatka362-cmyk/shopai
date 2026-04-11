"""AgentLoader — dynamic import and caching of agent instances."""

from __future__ import annotations

import importlib
import threading
from typing import Any


class AgentLoader:
    """Dynamically loads agents by dotted class path, with instance caching.

    The previous implementation cached the imported CLASS but
    returned `cls()` (a fresh instance) on every load() call.
    For stateful agents like BaseAgent — which carries
    `_history` and learns across calls — this silently threw
    away every prior call's experience the next time the same
    agent name was loaded. The cache now stores the constructed
    instance so the same name returns the same singleton.
    """

    def __init__(self, registry=None) -> None:
        # Cached instances, not classes. Same name → same object.
        self._cache: dict[str, Any] = {}
        # Lock guarding _cache so concurrent load() calls don't
        # double-import + double-construct the same agent.
        self._lock = threading.Lock()
        self._registry = registry  # optional AgentRegistry instance

    @staticmethod
    def _import_class(class_path: str) -> type:
        """Import a class from a dotted path like 'agents.foo.bar.MyAgent'.

        Splits on the last dot: module path vs class name.
        """
        if "." not in class_path:
            raise ImportError(
                f"Invalid class path (need 'module.ClassName'): {class_path}"
            )

        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)

        if not hasattr(module, class_name):
            raise ImportError(
                f"Module '{module_path}' has no attribute '{class_name}'"
            )

        cls = getattr(module, class_name)
        if not isinstance(cls, type):
            raise TypeError(f"'{class_path}' is not a class (got {type(cls).__name__})")

        return cls

    def _resolve_class_path(self, agent_name: str) -> str:
        """Resolve a registered name → dotted class path."""
        if self._registry is not None:
            entry = self._registry.lookup(agent_name)
            return entry.get("class_path") or agent_name
        return agent_name

    def load(self, agent_name: str) -> object:
        """Load an agent and return its singleton instance.

        If a registry is attached, looks up *agent_name* to find
        the class path. Otherwise *agent_name* is treated as a
        dotted class path directly. The constructed instance is
        cached so the SAME name returns the SAME object on
        subsequent calls — preserving any learned history,
        in-progress run state, etc.
        """
        # Fast path: already cached
        with self._lock:
            cached = self._cache.get(agent_name)
            if cached is not None:
                return cached

        # Slow path: resolve, import, construct
        class_path = self._resolve_class_path(agent_name)
        cls = self._import_class(class_path)
        instance = cls()

        # Re-check inside the lock so concurrent first-loads
        # converge on the same singleton instead of one
        # silently overwriting the other.
        with self._lock:
            existing = self._cache.get(agent_name)
            if existing is not None:
                return existing
            self._cache[agent_name] = instance
            return instance

    def load_all(self, agent_names: list[str]) -> dict[str, object]:
        """Load multiple agents and return a mapping of name -> instance."""
        results: dict[str, object] = {}
        for name in agent_names:
            results[name] = self.load(name)
        return results

    def reload(self, agent_name: str) -> object:
        """Force-reload an agent (bypasses cache, reimports module).

        Discards the prior cached instance and constructs a fresh
        one from the reloaded module. Existing references that
        other code holds to the OLD instance are NOT updated;
        callers that need a hot-swap should re-fetch via load()
        after this call.
        """
        class_path = self._resolve_class_path(agent_name)
        module_path, _ = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        importlib.reload(module)

        cls = self._import_class(class_path)
        instance = cls()
        with self._lock:
            self._cache[agent_name] = instance
        return instance

    def clear_cache(self) -> None:
        """Drop all cached instances. Useful for tests + restarts."""
        with self._lock:
            self._cache.clear()
