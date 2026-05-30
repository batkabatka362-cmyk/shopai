"""Discoverer registry entry-point (W821).

Importing this module triggers the import of every per-domain
discoverer module, each of which calls ``register_discoverer``
at import time. Cycle controller + CLI surfaces import this
module once at startup to populate the registry.

Each new substrate domain's discoverer adds a single import
line here.
"""
from __future__ import annotations

# Per-domain discoverers self-register at import time.
from core.automation.discoverers import (  # noqa: F401
    catalog_quality,
    customer_outreach,
    discount_cleanup,
    fulfillment,
    inventory,
    order_followup,
    product_seo,
    shipping_alert,
)
