"""Store Setup engine package.

Bridges autonomous setup decisions (policy text generation,
branding, content templates) into actual Shopify writes via
the standard adapter layer. The classic ``StoreConfigurator``
in ``execution/store_configurator.py`` handles the procedural
"create collections, set up discounts" wizard; this package
holds the AGI-driven helpers that need engine + router access.

Modules:
  * ``launch_audit`` -- read-only check: which launch-readiness
    items are done vs missing on a live store. Single-source-of-
    truth for "is this store ready to take orders?".
"""
