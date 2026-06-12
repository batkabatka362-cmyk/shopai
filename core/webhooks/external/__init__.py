"""W963-147: unified external webhook ingestion.

The Shopify webhook handler (W963-128) handles ONE vendor.
Tier 2 adapter expansion adds N more vendors (Gorgias,
AfterShip, GA4, Klaviyo, etc.), each with its own:

  - Auth scheme (Gorgias HMAC, Klaviyo HMAC, AfterShip
    secret in path, GA4 IP whitelist + no auth)
  - Event payload schema
  - Topic naming convention
  - Store-identifying field (some send shop URL, some
    send tenant_id, some require lookup via order_id)

Without a unified ingestion layer, every adapter would
re-implement the same plumbing. This package collapses
it into:

  - VendorHandler: per-vendor adapter (validates auth,
    extracts topic + store_id, normalises payload)
  - ExternalWebhookHandler: dispatcher (routes
    topic -> engine + wraps engine.run in active_store)
  - EVENT_ENGINE_MAP: vendor-prefixed topic -> engine
    name list

Pattern CD audit (W963-141) compatible: engine.run
inside `with active_store(sid):` wrap when the vendor
handler resolves a sid.
"""
from .handler import (
    EVENT_ENGINE_MAP,
    ExternalWebhookHandler,
    VendorHandler,
    WebhookOutcome,
)
from .vendors.aftership import AfterShipVendorHandler
from .vendors.ga4 import GA4VendorHandler
from .vendors.gorgias import GorgiasVendorHandler
from .vendors.stripe import StripeVendorHandler

__all__ = [
    "EVENT_ENGINE_MAP",
    "ExternalWebhookHandler",
    "VendorHandler",
    "WebhookOutcome",
    "AfterShipVendorHandler",
    "GA4VendorHandler",
    "GorgiasVendorHandler",
    "StripeVendorHandler",
]
