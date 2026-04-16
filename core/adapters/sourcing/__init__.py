"""Sourcing / dropshipping-supplier adapters.

A *sourcing* adapter wraps a supplier-side catalog + fulfillment
API. CJ Dropshipping is the primary integration (free developer
API, MN-friendly). AutoDS, Spocket, Zendrop will slot in here.

See :class:`core.adapters.sourcing._base.SourcingBaseAdapter` for
the shared base class and :func:`bootstrap.register_all` for the
process-wide registrar.
"""
from ._base import SourcingBaseAdapter
from .cj_dropshipping import CJDropshippingAdapter

__all__ = ["SourcingBaseAdapter", "CJDropshippingAdapter"]
