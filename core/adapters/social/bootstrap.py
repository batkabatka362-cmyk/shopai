"""Social adapter bootstrap."""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .facebook_page import FacebookPageAdapter
from .instagram import InstagramAdapter

logger = get_logger("adapters.social.bootstrap")


_SOCIAL_ADAPTER_CLASSES = (
    InstagramAdapter,
    FacebookPageAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    reg = registry or get_registry()
    status: dict[str, bool] = {}
    for cls in _SOCIAL_ADAPTER_CLASSES:
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
            status[adapter.name] = adapter.is_configured()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to register %s: %s",
                adapter.name, exc,
            )
    return status
