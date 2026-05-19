"""Store Setup engine package.

Bridges autonomous setup decisions (policy text generation,
branding, content templates) into actual Shopify writes via
the standard adapter layer. The classic ``StoreConfigurator``
in ``execution/store_configurator.py`` handles the procedural
"create collections, set up discounts" wizard; this package
holds the AGI-driven helpers that need engine + router access.

Modules:
  * ``policy_generator`` -- niche/jurisdiction-aware legal
    policy body generation (REFUND / PRIVACY / TERMS / etc.).
  * ``policy_applier`` -- pushes generated policies via
    ``SHOPIFY_UPDATE_SHOP_POLICY`` (adapter from PR #363).
"""
