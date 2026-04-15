"""Ads-spy adapter bootstrap.

Registers every ads intelligence adapter in the process-wide
registry. Safe to call repeatedly (replace=True ensures hot-
reload on key rotation). Unconfigured adapters stay registered
so the router can enumerate them for the operator dashboard,
but are skipped when resolving capabilities (the base registry
sort puts configured adapters first, unconfigured last).
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .bigspy import BigSpyAdapter
from .facebook_ads_library import FacebookAdsLibraryAdapter
from .minea import MineaAdapter
from .pipiads import PiPiAdsAdapter

logger = get_logger("adapters.ads_spy.bootstrap")


_SPY_ADAPTER_CLASSES = (
    MineaAdapter,
    PiPiAdsAdapter,
    BigSpyAdapter,
    FacebookAdsLibraryAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every ads-spy adapter and register it.

    Returns a ``{adapter_name: is_configured}`` map so callers
    (typically ``core/adapters/bootstrap.py``) can log / report
    how many spy sources the process has active credentials for.
    """
    reg = registry or get_registry()
    status: dict[str, bool] = {}

    for cls in _SPY_ADAPTER_CLASSES:
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
        "Ads-spy adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
