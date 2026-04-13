"""Obsidian vault adapter bootstrap.

Instantiates and registers the Obsidian adapter with the
global ``AdapterRegistry``. Follows the same pattern as
``core/adapters/search/bootstrap.py``.

Usage::

    from core.adapters.obsidian.bootstrap import register_all
    register_all()

The adapter registers even when ``OBSIDIAN_VAULT_PATH`` is
unset — the smart router skips it via ``is_configured()``.
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .vault import ObsidianVaultAdapter

logger = get_logger("adapters.obsidian.bootstrap")


_OBSIDIAN_ADAPTER_CLASSES = (
    ObsidianVaultAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every Obsidian adapter and register it.

    Returns a ``{adapter_name: is_configured}`` map.
    """
    reg = registry or get_registry()
    status: dict[str, bool] = {}

    for cls in _OBSIDIAN_ADAPTER_CLASSES:
        try:
            adapter = cls()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to instantiate %s: %s", cls.__name__, exc,
            )
            continue

        try:
            reg.register(adapter, replace=True)
            status[adapter.name] = adapter.is_configured()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to register %s: %s", adapter.name, exc,
            )

    configured = sum(1 for v in status.values() if v)
    logger.info(
        "Obsidian adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
