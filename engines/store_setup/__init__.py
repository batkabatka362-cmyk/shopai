"""Store Setup engine package.

Bridges autonomous setup decisions into actual Shopify writes
via the standard adapter layer. The classic ``StoreConfigurator``
in ``execution/store_configurator.py`` handles the procedural
"create collections, set up discounts" wizard; this package
holds the AGI-driven helpers that need engine + router access.

Modules:
  * ``brand_uploader`` -- push logo / favicon / hero / og_image
    URLs to Shopify Files via ``SHOPIFY_UPLOAD_FILE``.
  * ``collection_seeder`` -- niche-aware starter collections
    via ``SHOPIFY_CREATE_COLLECTION``.
  * ``launch_audit`` -- read-only check: which launch-readiness
    items are done vs missing on a live store.
  * ``launch_orchestrator`` -- single-command autonomous launch.
  * ``metaobject_definitions`` -- niche-aware metaobject
    type definitions (Ingredient / Material / Recipe /
    Stone / Stage / ...). Pushes via
    ``SHOPIFY_CREATE_METAOBJECT_DEFINITION``.
  * ``page_generator`` / ``page_applier`` -- niche-aware
    About / Contact / FAQ / Shipping pages via
    ``SHOPIFY_CREATE_PAGE``.
  * ``policy_generator`` / ``policy_applier`` -- niche +
    region aware legal policies via
    ``SHOPIFY_UPDATE_SHOP_POLICY``.
  * ``product_description_enricher`` -- niche-aware product
    description generation via ``SHOPIFY_UPDATE_PRODUCT``.
  * ``seo_meta_enricher`` -- niche-aware product SEO meta
    (title_tag + meta_description) via ``SHOPIFY_UPDATE_PRODUCT``.
  * ``welcome_discount`` -- launch-time WELCOME{N} code via
    ``SHOPIFY_CREATE_DISCOUNT``.
"""
