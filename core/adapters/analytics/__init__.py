"""W963-146: analytics adapter category.

Initial vendor: GA4 (Google Analytics 4) via Measurement
Protocol. Future: Mixpanel, Posthog, Plausible, Hotjar,
Microsoft Clarity.

Used by ShopAI to:
  - Send conversion / purchase / add_to_cart events
    when adapters fire writes (multi-touch attribution
    across channels)
  - Mirror Shopify webhook events to GA4 so cross-
    channel attribution doesn't depend only on
    Shopify's built-in tracking
  - Identify users for cross-device measurement

Per-store routing via active_store + W963-117 helper:
  SHOPAI_STORE_<SID>_GA4_MEASUREMENT_ID / SECRET.
"""
from ._base import AnalyticsBaseAdapter

__all__ = ["AnalyticsBaseAdapter"]
