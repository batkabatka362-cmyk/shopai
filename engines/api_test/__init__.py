"""W963-112: shopai api-test -- live health check per adapter.

For each adapter that has credentials configured, make a
single minimal real API call and report success / failure
with latency + concrete error message. Catches:

  * Wrong env-var value (operator pasted incorrectly)
  * Endpoint URL drift (vendor moved the API)
  * Permission gaps (key issued without required scope)
  * Network / DNS / TLS issues
  * Adapter request shape bugs (W963-103 etc. shipped
    skeletons; first live call surfaces shape errors)

Run BEFORE shopai cycle run --yes to catch configuration
issues without paying the cost of a failed autonomous
cycle.
"""
from .flow import ApiTestEngine

__all__ = ["ApiTestEngine"]
