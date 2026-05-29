"""Per-domain payload discoverers (W821+).

Each module under this package implements one autonomy
domain's discoverer + registers itself with the
``payload_discoverer`` registry at import time.

The parent ``discoverer_registry`` module imports every
submodule here so the registry is populated on demand.
"""
