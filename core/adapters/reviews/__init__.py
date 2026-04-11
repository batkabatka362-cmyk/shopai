"""Product reviews adapter family.

Concrete adapters live here (Judge.me today; Yotpo, Loox,
Stamped, Okendo later). They share the
:class:`ReviewsBaseAdapter` skeleton and wire into the router
through :func:`core.adapters.reviews.bootstrap.register_all`.

Reviews sit under ``AdapterCategory.SHOPIFY_APP`` — every
vendor in this family is, functionally, a third-party Shopify
App that happens to expose a vendor REST API on the side.
Keeping them in their own directory prevents them from being
confused with ``core/adapters/shopify/`` (native Shopify
Admin / GraphQL endpoints).
"""
from __future__ import annotations

from ._base import ReviewsBaseAdapter
from .judgeme import JudgeMeAdapter

__all__ = [
    "ReviewsBaseAdapter",
    "JudgeMeAdapter",
]
