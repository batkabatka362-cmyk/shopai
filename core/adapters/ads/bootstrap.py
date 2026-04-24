"""Ads adapter bootstrap.

Real placement adapters:
  * MetaAdsAdapter — Facebook / Instagram / Audience Network
  * TikTokAdsAdapter — TikTok for Business Marketing API v1.3

Google Ads research stubs live in ``ads_spy``; a real Google
Ads adapter is out of scope until we have the developer-token
+ OAuth refresh flow approved.
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .meta_ads import MetaAdsAdapter
from .tiktok_ads import TikTokAdsAdapter

logger = get_logger("adapters.ads.bootstrap")


_ADS_ADAPTER_CLASSES = (MetaAdsAdapter, TikTokAdsAdapter)


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
