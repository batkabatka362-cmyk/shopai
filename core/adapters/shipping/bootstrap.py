"""Shipping adapter bootstrap.

Single entry point that instantiates every shipping adapter
and registers it with ``AdapterRegistry``. Mirrors the LLM /
Shopify / search bootstraps so the controller can call all
four at startup with the same idempotency guarantees.

Usage::

    from core.adapters.shipping.bootstrap import register_all
    register_all()

Adapters whose API key is unset still register; the smart
router skips them via ``is_configured()``. Unlike DDGS in the
search layer, shipping adapters all require an API key — there
is no "no-key default" here. Operators must wire at least one
of EasyPost / Shippo before the brain can fetch shipping rates.
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .easypost import EasyPostAdapter
from .shippo import ShippoAdapter

logger = get_logger("adapters.shipping.bootstrap")


_SHIPPING_ADAPTER_CLASSES = (
    EasyPostAdapter,
    ShippoAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every shipping adapter and register it.

    Returns a ``{adapter_name: is_configured}`` map.
    """
    reg = registry or get_registry()
    status: dict[str, bool] = {}

    for cls in _SHIPPING_ADAPTER_CLASSES:
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
        "Shipping adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
