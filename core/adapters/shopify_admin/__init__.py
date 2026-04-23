"""Unified Shopify Admin API client.

Replaces the 4 concurrent Shopify HTTP wrappers that grew over
time (``core/bridge/shopify_connector.py``, ``scripts/
_shopify_client.py``, ``execution/shopify_store_manager.py``,
``execution/shopify_automation.py``) with one canonical client
+ one resource module per Shopify domain.

Owner's frame (CORE vs COMMODITY):

  * ``client.py``       — CORE plumbing (retry, rate limit,
                          auth, envelope unwrap). Build ours.
  * Resource modules    — CORE logic (what combination of
                          endpoints does it take to "create a
                          discount code"? — that's our policy,
                          not the vendor's).
  * Shopify REST/GQL    — COMMODITY surface. Version bump
                          lives in ``ShopifyAdminClient``
                          constructor only.

Resource modules so far:

  * ``discounts``    — price rules + discount codes
  * ``inventory``    — levels + set + adjust
  * ``draft_orders`` — create / complete / send_invoice

More land as the engines call for them — ``fulfillments``,
``refunds``, ``customers``, ``markets``, etc. Same pattern
(class with static/instance methods taking a ``ShopifyAdminClient``)
so adding another resource is 100-200 LOC.

Usage::

    from core.adapters.shopify_admin import ShopifyAdminClient
    from core.adapters.shopify_admin.discounts import Discounts

    client = ShopifyAdminClient.from_env()

    rule = Discounts.create_percentage_code(
        client,
        code="SUMMER20",
        value_pct=20,
        title="Summer 2026 sale",
        once_per_customer=True,
    )

All modules are pure — no global state, no module-level
singletons. Callers that want a shared instance pass the same
``client`` around; tests pass a fake.
"""
from core.adapters.shopify_admin.client import (
    ShopifyAdminClient,
    ShopifyAdminError,
    ShopifyAdminMisconfigured,
)

__all__ = [
    "ShopifyAdminClient",
    "ShopifyAdminError",
    "ShopifyAdminMisconfigured",
]
