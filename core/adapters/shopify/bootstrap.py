"""Shopify Native adapter bootstrap.

Single entry point that instantiates every Shopify native
adapter and registers it with ``AdapterRegistry``. Mirrors
``core.adapters.llm.bootstrap`` so the controller can call
both at startup with the same idempotency guarantees.

Usage::

    from core.adapters.shopify.bootstrap import register_all
    register_all()                            # use AdapterConfig env vars
    register_all(shop_url="...", access_token="...")  # explicit creds

Adapters whose credentials are unset still register with the
registry; the smart router skips them via ``is_configured()``.
This means a freshly-bootstrapped controller can list every
Shopify adapter via ``registry.list()`` even before the operator
has wired up Shopify credentials.
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .discounts import ShopifyDiscountAdapter
from .draft_orders import ShopifyDraftOrdersAdapter
from .files import ShopifyFilesAdapter
from .fulfillment import ShopifyFulfillmentAdapter
from .inventory import ShopifyInventoryAdapter
from .marketing_events import ShopifyMarketingEventsAdapter
from .metafield import ShopifyMetafieldAdapter
from .metaobjects import ShopifyMetaobjectsAdapter
from .returns import ShopifyReturnsAdapter
from .risk import ShopifyRiskAdapter

logger = get_logger("adapters.shopify.bootstrap")


_SHOPIFY_ADAPTER_CLASSES = (
    ShopifyRiskAdapter,
    ShopifyInventoryAdapter,
    ShopifyFulfillmentAdapter,
    ShopifyMetafieldAdapter,
    ShopifyDiscountAdapter,
    ShopifyFilesAdapter,
    ShopifyDraftOrdersAdapter,
    ShopifyMarketingEventsAdapter,
    ShopifyReturnsAdapter,
    ShopifyMetaobjectsAdapter,
)


def register_all(
    shop_url: str | None = None,
    access_token: str | None = None,
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every Shopify native adapter and register it.

    Args:
        shop_url: Optional shop URL to override the one from
            ``AdapterConfig``. Useful for multi-store setups
            where each store needs its own adapter instance.
        access_token: Optional access token override.
        registry: Optional explicit registry (test injection).

    Returns:
        ``{adapter_name: is_configured}`` map.
    """
    reg = registry or get_registry()
    status: dict[str, bool] = {}

    for cls in _SHOPIFY_ADAPTER_CLASSES:
        try:
            adapter = cls(shop_url=shop_url, access_token=access_token)
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
        "Shopify native adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
