"""Advertising adapters.

Each adapter wraps a single ad platform in the universal
``BaseAdapter`` interface so the brain can route to it via
``Capability.ADS_CREATE_CAMPAIGN``, ``ADS_GET_PERFORMANCE``,
or ``ADS_UPDATE_BUDGET``:

  * ``google_ads`` — Google Ads API (Search, Display, Shopping)
  * ``meta_ads``   — Meta (Facebook/Instagram) Marketing API

Bootstrap::

    from core.adapters.ads.bootstrap import register_all
    register_all()
"""
from ._base import AdsBaseAdapter

__all__ = ["AdsBaseAdapter"]
