"""Ads adapter bootstrap.

Only Meta Ads has a concrete adapter today (``meta_ads.py``).
Google Ads / TikTok Ads stubs live in ``ads_spy`` for research;
this bootstrap registers the real placement adapters.
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .meta_ads import MetaAdsAdapter

logger = get_logger("adapters.ads.bootstrap")


_ADS_ADAPTER_CLASSES = (MetaAdsAdapter,)


def register_all(registry: AdapterRegistry | None = None) -> dict[str, bool]:
    reg = registry or get_registry()
    status: dict[str, bool] = {}
    for cls in _ADS_ADAPTER_CLASSES:
        try:
            adapter = cls()
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to instantiate %s: %s", cls.__name__, exc)
            continue
        try:
            reg.register(adapter, replace=True)
            status[adapter.name] = adapter.is_configured()
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to register %s: %s", adapter.name, exc)
    configured = sum(1 for v in status.values() if v)
    logger.info(
        "Ads adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
