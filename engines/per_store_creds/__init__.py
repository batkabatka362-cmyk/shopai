"""W963-142: per-store credential coverage discovery.

Lists which per-store env-var overrides each store has
set. For a 20-store empire, operator runs `shopai
store-creds` to see at a glance:

  store_a: openai, klaviyo, meta_ads
  store_b: openai
  store_c: (using fleet defaults)
  ...

Built on top of W963-116's _normalise_sid_for_env so the
discovery matches the resolution chain. Pure read-only;
no Pattern J / Pattern Z concerns.
"""
from .coverage import (
    StoreCoverage,
    discover_coverage,
)
from .flow import PerStoreCredsEngine

__all__ = [
    "PerStoreCredsEngine",
    "StoreCoverage",
    "discover_coverage",
]
