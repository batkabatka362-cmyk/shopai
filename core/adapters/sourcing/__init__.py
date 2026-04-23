"""Sourcing / dropshipping-supplier adapters.

A *sourcing* adapter wraps a supplier-side catalog + fulfillment
API. CJ Dropshipping is the primary integration (free developer
API, MN-friendly). AutoDS slots in as the paid-tier fallback
(US warehouse + multi-marketplace sourcing). Spocket, Zendrop
will join here.

See :class:`core.adapters.sourcing._base.SourcingBaseAdapter` for
the shared base class and :func:`bootstrap.register_all` for the
process-wide registrar.
"""
from ._base import SourcingBaseAdapter
from .autods import AutoDSAdapter
from .cj_dropshipping import CJDropshippingAdapter

__all__ = [
    "SourcingBaseAdapter",
    "AutoDSAdapter",
    "CJDropshippingAdapter",
]
