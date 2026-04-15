"""Ads intelligence / spy adapters.

Each adapter wraps a single ad-spy data source in the universal
``BaseAdapter`` interface so the winning-product detection
engine can aggregate across sources without vendor lock-in.

Capabilities exposed:

  * :attr:`Capability.ADS_SPY_SEARCH`        — search ads by
                                                 keyword / country
  * :attr:`Capability.ADS_SPY_TOP_PRODUCTS`  — trending products
                                                 by engagement /
                                                 days_running
  * :attr:`Capability.ADS_SPY_AD_DETAILS`    — single ad deep-
                                                 dive

Sources (priority-ordered):

  * ``minea``           — dropshipping-focused paid API ($49/mo)
  * ``pipiads``         — TikTok-focused paid API ($77/mo)
  * ``bigspy``          — broad-coverage paid API ($99/mo; free
                          tier for low volumes)
  * ``fb_ads_library``  — Meta's public ad-transparency feed
                          (free; optional token unlocks higher
                          rate limits)

Every adapter returns the same :func:`AdsSpyBaseAdapter.
_normalise_record` shape so the winning-product engine is
vendor-agnostic.

Bootstrap::

    from core.adapters.ads_spy.bootstrap import register_all
    register_all()
"""
from ._base import AdsSpyBaseAdapter

__all__ = ["AdsSpyBaseAdapter"]
