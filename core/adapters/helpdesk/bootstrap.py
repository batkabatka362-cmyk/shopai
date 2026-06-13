"""Helpdesk adapter bootstrap (W963-145).

Idempotent registration mirroring shipping/tracking
bootstraps."""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .gorgias import GorgiasAdapter

logger = get_logger("adapters.helpdesk.bootstrap")


_HELPDESK_ADAPTER_CLASSES = (
    GorgiasAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    reg = (
        registry
        if registry is not None
        else get_registry()
    )
    status: dict[str, bool] = {}

    for cls in _HELPDESK_ADAPTER_CLASSES:
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

    configured = sum(
        1 for v in status.values() if v
    )
    logger.info(
        "Helpdesk adapters registered: %d total, "
        "%d configured",
        len(status), configured,
    )
    return status
