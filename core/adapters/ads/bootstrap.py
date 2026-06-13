"""Ads adapter bootstrap.

Single entry point that instantiates every ad-platform adapter
and registers it with ``AdapterRegistry``. Mirrors the LLM /
Shopify / email / search / shipping bootstraps so the
controller can call all of them at startup with the same
idempotency guarantees.

Usage::

    from core.adapters.ads.bootstrap import register_all
    register_all()

Ad platform adapters require platform-specific credentials
(Meta: long-lived access token + ad account ID; Google:
OAuth refresh token + customer ID). Adapters whose creds
are unset still register; the smart router skips them via
``is_configured()``.
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .google_ads import GoogleAdsAdapter
from .meta_ads import MetaAdsAdapter

logger = get_logger("adapters.ads.bootstrap")


_ADS_ADAPTER_CLASSES = (
    MetaAdsAdapter,
    GoogleAdsAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every ad adapter and register it.

    Returns a ``{adapter_name: is_configured}`` map.
    """
    # NOTE: ``registry or get_registry()`` is buggy because an
    # empty AdapterRegistry is falsy (__len__ returns 0). Use
    # explicit None-check so callers that pass an empty registry
    # actually get THEIR registry populated, not the global
    # singleton. Other bootstraps (email/llm/shopify) have the
    # same latent bug but tests there typically use the
    # singleton, so it's not visible.
    reg = registry if registry is not None else get_registry()
    status: dict[str, bool] = {}

    for cls in _ADS_ADAPTER_CLASSES:
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
        "Ads adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
