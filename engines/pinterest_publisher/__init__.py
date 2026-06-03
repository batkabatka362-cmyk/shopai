"""Pinterest Publisher Engine — W963-10.

Operator-facing wrapper around PinterestAdapter. Mirrors the
W963-7 ads_launcher + W963-8 email_connect pattern:

  shopai pinterest status                       -- is it wired?
  shopai pinterest connect --token X            -- save creds to .env
  shopai pinterest boards                       -- list existing boards
  shopai pinterest publish-pin --board-id B \\
       --title T --image-url U [--link L]       -- publish single pin

The engine deliberately publishes ONE pin at a time. Bulk
publishing trips Pinterest's spam-detection ML; the autonomous
loop should fire one pin per cycle which sits well below the
~10/min soft limit.

Why Pinterest first:
  - Pins surface in search for months / years (long-tail SEO)
  - Direct shopping intent (the user is actively browsing
    products when discovering pins)
  - Lower platform velocity than IG / TikTok = lower content
    cost per discovery
  - Beauty / fashion / home niches dominate the platform
"""
from .flow import PinterestPublisherEngine

__all__ = ["PinterestPublisherEngine"]
