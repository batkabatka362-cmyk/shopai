"""LX.5 multi-store federation — owner-facing singleton + wiring.

Thin accessor for ``core.brain.multi_store_federator.MultiStoreFederator``
that adds:

  * SQLite persistence at ``data/federation.db`` so state survives
    restarts (the federator supports a ``db_path`` but the
    brain_facade's internal accessor uses in-memory mode).
  * A module-level singleton so the CLI, notify hooks, and any
    future autopilot wire-in all share one federator.
  * A reset helper for tests.

See docs/AGI_STACK.md LX.5 for the rationale: one brain, N stores —
rules learned at store A propagate to store B via similarity
weighting.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from core.brain.multi_store_federator import (
    FederationReport,
    MultiStoreFederator,
    RuleObservation,
    StoreSpec,
)

__all__ = [
    "FederationReport",
    "MultiStoreFederator",
    "RuleObservation",
    "StoreSpec",
    "get_federator",
    "reset_federator_for_tests",
]


_SINGLETON: MultiStoreFederator | None = None
_SINGLETON_LOCK = threading.Lock()
_DEFAULT_DB_PATH = Path("data/federation.db")


def get_federator(
    db_path: str | Path | None = None,
) -> MultiStoreFederator:
    """Return (creating if needed) the module-level federator.

    ``db_path`` is honoured only on the first call — subsequent
    calls return the cached instance. Use
    ``reset_federator_for_tests`` to force rebuild.
    """
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                path = (
                    Path(db_path)
                    if db_path is not None
                    else _DEFAULT_DB_PATH
                )
                path.parent.mkdir(
                    parents=True, exist_ok=True,
                )
                _SINGLETON = MultiStoreFederator(
                    db_path=path,
                )
    return _SINGLETON


def reset_federator_for_tests() -> None:
    """Clear the module-level singleton (test-only helper)."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            try:
                _SINGLETON.close()
            except Exception as exc:  # noqa: BLE001
                from utils.logger import get_logger
                get_logger("core.federation").debug(
                    "reset_federator close skipped: %s",
                    exc,
                )
        _SINGLETON = None
