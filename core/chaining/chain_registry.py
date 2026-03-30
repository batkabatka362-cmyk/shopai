"""ChainRegistry — stores and retrieves named engine chains.

Chains are reusable workflows. Registry never modifies engine code.
"""
from __future__ import annotations

import threading
from typing import Any

from utils.logger import get_logger
from .engine_chain import EngineChain
from .chain_builder import ChainBuilder

logger = get_logger("chaining.registry")


class ChainRegistry:
    """Thread-safe registry of named engine chains."""

    def __init__(self) -> None:
        self._chains: dict[str, EngineChain] = {}
        self._lock = threading.Lock()
        self._register_defaults()

    def register(self, name: str, chain: EngineChain) -> None:
        """Register a chain by name."""
        with self._lock:
            self._chains[name] = chain
        logger.info("Registered chain: %s", name)

    def get(self, name: str) -> EngineChain:
        """Get a chain by name."""
        with self._lock:
            if name not in self._chains:
                raise KeyError(f"Unknown chain: {name}")
            return self._chains[name]

    def list_chains(self) -> list[str]:
        """List all registered chain names."""
        with self._lock:
            return sorted(self._chains.keys())

    def run(self, name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Get and run a chain by name."""
        chain = self.get(name)
        return chain.run(data)

    def _register_defaults(self) -> None:
        """Register pre-built chains."""
        defaults = {
            "product_launch": ChainBuilder.product_launch,
            "customer_acquisition": ChainBuilder.customer_acquisition,
            "inventory_restock": ChainBuilder.inventory_restock,
            "customer_retention": ChainBuilder.customer_retention,
        }
        for name, factory in defaults.items():
            self._chains[name] = factory()
