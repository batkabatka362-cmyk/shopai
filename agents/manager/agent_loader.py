"""AgentLoader — dynamic import and caching of agent classes."""

from __future__ import annotations

import importlib


class AgentLoader:
    """Dynamically loads agent classes by dotted class path, with caching."""

    def __init__(self, registry=None) -> None:
        self._cache: dict[str, type] = {}
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

    def load(self, agent_name: str) -> object:
        """Load an agent class by registry name and return an instance.

        If a registry is attached, looks up *agent_name* to find the class path.
        Otherwise *agent_name* is treated as a dotted class path directly.
        """
        if agent_name in self._cache:
            return self._cache[agent_name]()

        if self._registry is not None:
            entry = self._registry.lookup(agent_name)
            class_path = entry["class_path"]
        else:
            class_path = agent_name

        cls = self._import_class(class_path)
        self._cache[agent_name] = cls
        return cls()

    def load_all(self, agent_names: list[str]) -> dict[str, object]:
        """Load multiple agents and return a mapping of name -> instance."""
        results: dict[str, object] = {}
        for name in agent_names:
            results[name] = self.load(name)
        return results

    def reload(self, agent_name: str) -> object:
        """Force-reload an agent class (bypasses cache, reimports module)."""
        if self._registry is not None:
            entry = self._registry.lookup(agent_name)
            class_path = entry["class_path"]
        else:
            class_path = agent_name

        module_path, _ = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        importlib.reload(module)

        cls = self._import_class(class_path)
        self._cache[agent_name] = cls
        return cls()
