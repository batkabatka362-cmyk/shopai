"""Product analytics adapters.

  * ``posthog``  — PostHog product analytics
  * ``mixpanel`` — Mixpanel user behavior analytics

Bootstrap::

    from core.adapters.analytics.bootstrap import register_all
    register_all()
"""
from ._base import AnalyticsBaseAdapter

__all__ = ["AnalyticsBaseAdapter"]
