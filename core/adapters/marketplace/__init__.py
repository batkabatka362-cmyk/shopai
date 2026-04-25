"""Marketplace adapters — non-Shopify storefronts.

First member: ``AmazonSPAdapter`` (Z6 multi-platform mission).
eBay / Etsy / Walmart slot in here later with the same
shape.
"""
from core.adapters.marketplace.amazon_sp import (
    AmazonSPAdapter,
)

__all__ = ["AmazonSPAdapter"]
