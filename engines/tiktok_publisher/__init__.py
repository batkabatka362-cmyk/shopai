"""TikTok Publisher Engine — W963-12.

Operator-facing wrapper around TikTokAdapter. Mirrors the
W963-10 pinterest_publisher pattern:

  shopai tiktok status                                -- is it wired?
  shopai tiktok connect --token X --business-id Y     -- save creds
  shopai tiktok posts                                 -- list recent
  shopai tiktok publish-post --caption C --media-url U --type PHOTO

Why TikTok matters: second-largest visual social platform after
Pinterest for product discovery in beauty/fashion/home. TikTok's
algorithm favors high-velocity small accounts, so day-1 stores
can plausibly reach audiences faster than on Pinterest's slower
search-driven discovery.

One post per call -- spam protection. Future autonomous loop
fires one post per cycle.
"""
from .flow import TikTokPublisherEngine

__all__ = ["TikTokPublisherEngine"]
