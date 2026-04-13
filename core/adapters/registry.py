"""AdapterRegistry — thread-safe lego board for adapters.

Adapters are registered once at startup (or hot-loaded on demand)
and looked up by name OR by capability. The router uses the
capability lookup to choose the best adapter for each call.

Thread safety follows the same pattern as ``core/rate_limiter``
(audit pass 53): a single re-entrant lock protects every read
and write so concurrent ``register`` / ``find_by_capability`` /
``unregister`` calls do not race. ``RLock`` (not ``Lock``) is
used so a method that already holds the lock can call another
locked method without deadlocking — same gotcha that bit
``QuotaManager.get_all_quotas`` in pass 53.
"""
from __future__ import annotations

import threading
from typing import Iterable

from utils.logger import get_logger

from .base import BaseAdapter, Capability

logger = get_logger("adapters.registry")


class AdapterRegistry:
    """Process-wide adapter directory.

    Use ``register(adapter)`` to add an adapter, ``get(name)`` to
    fetch by name, ``find_by_capability(capability)`` to fetch
    every adapter that implements a given capability (sorted by
    priority, configured-first), and ``swap(old_name, new)`` to
    hot-swap an adapter without dropping calls in flight.

    The registry deliberately does NOT instantiate adapters on
    your behalf — caller code constructs the adapter (with its
    own credentials/config) and hands the instance over. This
    keeps test setup simple and avoids hidden global state.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, BaseAdapter] = {}
        self._lock = threading.RLock()

    # ── Mutation ────────────────────────────────────────────────

    def register(self, adapter: BaseAdapter, *, replace: bool = False) -> None:
        """Add *adapter* to the registry.

        Raises ``ValueError`` if an adapter with the same name is
        already registered, unless ``replace=True``. Replacement
        is the safer alternative to ``unregister`` + ``register``
        because it happens atomically under the registry lock.
        """
        if not isinstance(adapter, BaseAdapter):
            raise TypeError(
                f"register() expects BaseAdapter, got {type(adapter).__name__}",
            )
        with self._lock:
            if adapter.name in self._adapters and not replace:
                raise ValueError(
                    f"adapter {adapter.name!r} is already registered "
                    f"(pass replace=True to overwrite)",
                )
            self._adapters[adapter.name] = adapter
        logger.info(
            "registered adapter %r (%s, %d capabilities)",
            adapter.name, adapter.category.value, len(adapter.capabilities),
        )

    def unregister(self, name: str) -> bool:
        """Remove *name* from the registry. Returns True if it
        was present, False otherwise."""
        with self._lock:
            return self._adapters.pop(name, None) is not None

    def swap(self, old_name: str, new_adapter: BaseAdapter) -> BaseAdapter:
        """Atomically replace ``old_name`` with ``new_adapter``.

        Useful for vendor migration (e.g. swap Klaviyo adapter
        for Brevo adapter without restarting the process).
        Returns the previous adapter so the caller can audit /
        flush state.
        """
        with self._lock:
            previous = self._adapters.get(old_name)
            if previous is None:
                raise KeyError(f"no adapter named {old_name!r}")
            self._adapters.pop(old_name, None)
            self._adapters[new_adapter.name] = new_adapter
        logger.info(
            "swapped adapter %r → %r", old_name, new_adapter.name,
        )
        return previous

    def clear(self) -> None:
        """Drop every registered adapter. Primarily used by tests
        to get a clean slate between cases."""
        with self._lock:
            self._adapters.clear()

    # ── Lookup ──────────────────────────────────────────────────

    def get(self, name: str) -> BaseAdapter | None:
        """Return the adapter named ``name`` or ``None``."""
        with self._lock:
            return self._adapters.get(name)

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._adapters

    def find_by_capability(
        self,
        capability: Capability | str,
        *,
        configured_only: bool = True,
    ) -> list[BaseAdapter]:
        """Return every adapter that implements *capability*,
        sorted best-first.

        Sort order:
          1. Configured adapters before unconfigured ones
             (unless ``configured_only=True``, in which case
             unconfigured adapters are filtered out entirely).
          2. Higher ``priority`` first (default 50).
          3. Lower ``cost_per_call`` first (cheaper wins ties).
          4. Adapter name alphabetical (deterministic tiebreak).
        """
        if isinstance(capability, str):
            try:
                capability = Capability(capability)
            except ValueError:
                return []

        with self._lock:
            candidates = [
                a for a in self._adapters.values()
                if capability in a.capabilities
            ]

        if configured_only:
            candidates = [a for a in candidates if a.is_configured()]

        candidates.sort(
            key=lambda a: (
                # configured first (False < True so we want configured = 0)
                0 if a.is_configured() else 1,
                # higher priority first → negate
                -int(a.priority),
                # cheaper first
                float(a.cost_per_call),
                a.name,
            ),
        )
        return candidates

    def find_by_category(self, category: str) -> list[BaseAdapter]:
        """Return every adapter in *category*."""
        with self._lock:
            return [
                a for a in self._adapters.values()
                if a.category.value == category
            ]

    # ── Inspection ──────────────────────────────────────────────

    def list(self) -> list[dict]:
        """Return a JSON-serialisable description of every
        registered adapter. Suitable for ``GET /admin/adapters``
        observability endpoints."""
        with self._lock:
            return [a.describe() for a in self._adapters.values()]

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._adapters.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._adapters)

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        return self.has(name)

    def __iter__(self) -> Iterable[BaseAdapter]:
        with self._lock:
            return iter(list(self._adapters.values()))


# ── Module-level singleton ─────────────────────────────────────


_registry: AdapterRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> AdapterRegistry:
    """Return the process-wide adapter registry singleton.

    Lazy-initialised under a separate module lock to avoid race
    conditions when two threads call ``get_registry()`` at the
    same instant during startup.
    """
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = AdapterRegistry()
    return _registry


def reset_registry() -> None:
    """Replace the singleton with a fresh empty registry. Used
    by tests; never called from production code paths."""
    global _registry
    with _registry_lock:
        _registry = AdapterRegistry()
