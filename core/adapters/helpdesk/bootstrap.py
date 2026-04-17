"""Helpdesk adapter bootstrap.

Single entry point that instantiates every helpdesk adapter and
registers it with ``AdapterRegistry``.

Usage::

    from core.adapters.helpdesk.bootstrap import register_all
    register_all()
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .crisp import CrispAdapter
from .intercom import IntercomAdapter
from .zendesk import ZendeskAdapter

logger = get_logger("adapters.helpdesk.bootstrap")


_HELPDESK_ADAPTER_CLASSES = (
    IntercomAdapter,
    ZendeskAdapter,
    CrispAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every helpdesk adapter and register it.

    Returns a ``{adapter_name: is_configured}`` map.
    """
    reg = registry or get_registry()
    status: dict[str, bool] = {}

    for cls in _HELPDESK_ADAPTER_CLASSES:
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
        "Helpdesk adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
