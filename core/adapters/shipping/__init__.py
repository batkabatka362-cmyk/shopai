"""Shipping rate + label adapters.

Each adapter wraps a single carrier aggregator in the universal
``BaseAdapter`` interface so the brain can route to it via
``Capability.SHIPPING_RATE_QUOTE`` and
``Capability.SHIPPING_LABEL_BUY``:

  * ``easypost`` — EasyPost, **120,000 shipments/year FREE**
                   (the most generous free tier in the space)
  * ``shippo``   — Shippo, 30 labels/month free, more carriers

The shared ``ShippingBaseAdapter`` (in ``_base.py``) handles
HTTP plumbing and the normalised ``ShippingRate`` shape so
concrete adapters become 60-100 lines of vendor-specific URL
+ request body + parser.

Bootstrap::

    from core.adapters.shipping.bootstrap import register_all
    register_all()

Importing this package alone does NOT register anything — call
``bootstrap.register_all()`` so test isolation stays clean.
"""
from ._base import ShippingBaseAdapter, ShippingRate

__all__ = ["ShippingBaseAdapter", "ShippingRate"]
