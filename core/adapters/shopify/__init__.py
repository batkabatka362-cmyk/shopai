"""Shopify Native API adapters.

Each adapter wraps a small slice of Shopify's GraphQL Admin API
in the universal ``BaseAdapter`` interface so the brain can route
to it via capability:

  * ``risk``        — ``orderRiskAssessment`` (replaces the
                      deprecated REST ``order.risks`` endpoint)
  * ``inventory``   — multi-location ``inventoryLevels`` query
                      and ``inventorySetOnHandQuantities`` mutation
  * ``fulfillment`` — ``fulfillmentCreate`` mutation +
                      ``fulfillmentOrders`` query
  * ``metafield``   — extended metafield management for
                      orders / customers / variants

The shared ``ShopifyBaseAdapter`` (in ``_base.py``) handles auth
token resolution, GraphQL execution with retries, and error
mapping. Concrete adapters are 50-100 lines of capability + GraphQL
template + response parsing.

Usage::

    from core.adapters.shopify import bootstrap
    bootstrap.register_all(shop_url="store.myshopify.com",
                           access_token="shpat_...")

Importing this package alone does NOT register anything — call
``bootstrap.register_all()`` explicitly so test isolation stays
clean and credentials are passed in once.
"""
from ._base import ShopifyBaseAdapter

__all__ = ["ShopifyBaseAdapter"]
