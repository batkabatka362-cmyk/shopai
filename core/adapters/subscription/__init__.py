"""Subscription management adapters.

  * ``recharge`` — ReCharge Payments, the leading Shopify
    subscription platform

Bootstrap::

    from core.adapters.subscription.bootstrap import register_all
    register_all()
"""
from ._base import SubscriptionBaseAdapter

__all__ = ["SubscriptionBaseAdapter"]
