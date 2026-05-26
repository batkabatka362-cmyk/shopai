"""Sourcing adapter bootstrap.

Registers every sourcing / dropshipping-supplier adapter in the
process-wide registry. Safe to call repeatedly (replace=True
ensures hot-reload on credential rotation). Unconfigured adapters
stay registered for operator-dashboard enumeration but are skipped
when the router resolves capabilities (configured adapters are
sorted first).
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .cj_dropshipping import CJDropshippingAdapter

logger = get_logger("adapters.sourcing.bootstrap")


_SOURCING_ADAPTER_CLASSES = (
    CJDropshippingAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every sourcing adapter and register it.

    Returns a ``{adapter_name: is_configured}`` map so callers
    can log / report how many supplier APIs the process has
    active credentials for.
    """
    reg = registry if registry is not None else get_registry()
    status: dict[str, bool] = {}

    for cls in _SOURCING_ADAPTER_CLASSES:
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
        "Sourcing adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
