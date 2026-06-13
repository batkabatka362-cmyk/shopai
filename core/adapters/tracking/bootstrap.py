"""Tracking adapter bootstrap (W963-144).

Idempotent registration mirroring shipping/bootstrap.
The CLI startup calls register_all() so the smart router
sees AfterShip + future tracking aggregators.
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .aftership import AfterShipAdapter

logger = get_logger("adapters.tracking.bootstrap")


_TRACKING_ADAPTER_CLASSES = (
    AfterShipAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate + register every tracking adapter.

    Returns {adapter_name: is_configured}.
    """
    reg = (
        registry
        if registry is not None
        else get_registry()
    )
    status: dict[str, bool] = {}

    for cls in _TRACKING_ADAPTER_CLASSES:
        try:
            adapter = cls()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to instantiate %s: %s",
                cls.__name__, exc,
            )
            continue

        try:
            reg.register(adapter, replace=True)
            status[adapter.name] = (
                adapter.is_configured()
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to register %s: %s",
                adapter.name, exc,
            )

    configured = sum(1 for v in status.values() if v)
    logger.info(
        "Tracking adapters registered: %d total, "
        "%d configured",
        len(status), configured,
    )
    return status
